# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the "No Damage" constraint loss in ``bda.trainers``.

Two defects are covered here.

The first is the class layout: the loss used to hardcode ``y == 4`` and
``probs[:, 3]``, which silently computed the wrong objective for any project
whose class list didn't put "Damaged Building" third and "No Damage" fourth.

The second is what the loss actually constrains. Penalizing only
``p(Damaged Building)`` at "No Damage" pixels leaves every other channel free,
so the model can satisfy the objective by predicting the unsupervised
"No Damage" channel -- which is what happened in dev: inference emitted class
5. "No Damage" describes a building, not something visible in the imagery, so
it is never a legitimate prediction. The tests below pin down that the excluded
channels are actually driven to zero.
"""

import os
import sys
import unittest

import torch
import torch.nn.functional as F

# The `bda` package lives in the parent directory and is not installed.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from bda.trainers import constraint_segmentation_loss  # noqa: E402


def _reference_loss(
    y_hat, y, no_damage_index, damaged_class_index, ignore_index=0
):
    """Independent re-implementation used to check the helper."""
    ce = F.cross_entropy(y_hat, y, ignore_index=ignore_index, reduction="none")
    standard_mask = (y > 0) & (y != no_damage_index)
    loss = ce[standard_mask].mean()
    constraint_mask = y == no_damage_index
    if constraint_mask.any():
        excluded = {ignore_index, damaged_class_index, no_damage_index}
        allowed = [c for c in range(y_hat.shape[1]) if c not in excluded]
        probs = F.softmax(y_hat, dim=1)
        allowed_p = probs[:, allowed].sum(dim=1)
        loss = loss + (-torch.log(allowed_p))[constraint_mask].mean()
    return loss


def _fit_logits(
    y, num_classes, no_damage_index, damaged_class_index, steps=2000
):
    """Optimize raw logits against the loss and return the fitted softmax.

    No network in the way, so whatever the objective rewards is what this
    converges to.
    """
    torch.manual_seed(0)
    logits = torch.zeros(1, num_classes, *y.shape[1:], requires_grad=True)
    opt = torch.optim.Adam([logits], lr=0.1)
    for _ in range(steps):
        opt.zero_grad()
        loss = constraint_segmentation_loss(
            logits, y, no_damage_index, damaged_class_index
        )
        loss.backward()
        opt.step()
    return F.softmax(logits.detach(), dim=1), logits.detach().argmax(dim=1)


class TestConstraintSegmentationLoss(unittest.TestCase):
    def test_matches_reference_for_4_class_layout(self):
        """No Damage == 4 (a class list without a "Cloud" class)."""
        torch.manual_seed(0)
        y_hat = torch.randn(1, 5, 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [1, 2, 3, 4], [4, 4, 1, 2], [3, 2, 1, 4]]]
        )

        got = constraint_segmentation_loss(
            y_hat, y, no_damage_index=4, damaged_class_index=3
        )
        self.assertTrue(torch.allclose(got, _reference_loss(y_hat, y, 4, 3)))

    def test_matches_reference_for_5_class_layout(self):
        """No Damage == 5 (a class list that includes a "Cloud" class).

        This is the case the old hardcoded implementation got wrong: it would
        have treated mask value 4 as "No Damage" and lumped the real value 5
        into the standard cross-entropy term.
        """
        torch.manual_seed(1)
        y_hat = torch.randn(1, 6, 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )

        got = constraint_segmentation_loss(
            y_hat, y, no_damage_index=5, damaged_class_index=3
        )
        self.assertTrue(torch.allclose(got, _reference_loss(y_hat, y, 5, 3)))

    def test_differs_from_hardcoded_layout(self):
        """The 5-class result must not equal the old hardcoded computation."""
        torch.manual_seed(3)
        y_hat = torch.randn(1, 6, 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )

        correct = constraint_segmentation_loss(
            y_hat, y, no_damage_index=5, damaged_class_index=3
        )
        as_if_hardcoded = constraint_segmentation_loss(
            y_hat, y, no_damage_index=4, damaged_class_index=3
        )
        self.assertFalse(torch.allclose(correct, as_if_hardcoded))

    def test_damaged_class_index_is_honored(self):
        """The excluded channel follows damaged_class_index."""
        torch.manual_seed(5)
        y_hat = torch.randn(1, 6, 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )

        exclude_3 = constraint_segmentation_loss(
            y_hat, y, no_damage_index=5, damaged_class_index=3
        )
        exclude_4 = constraint_segmentation_loss(
            y_hat, y, no_damage_index=5, damaged_class_index=4
        )
        self.assertFalse(torch.allclose(exclude_3, exclude_4))

    # ── What the objective actually constrains ──────────────────────────────

    def test_no_damage_channel_is_driven_to_zero(self):
        """The regression behind the dev report: inference predicting class 5.

        "No Damage" is not a visual class, so the objective must make it an
        unattractive prediction at the very pixels it labels. The previous
        formulation left it at an even split with every other free channel.
        """
        # 1 Background, 2 Building, 3 Damaged, 4 Cloud, 5 No Damage.
        y = torch.tensor(
            [[[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 5, 5], [5, 5, 5, 5]]]
        )
        probs, pred = _fit_logits(
            y, num_classes=6, no_damage_index=5, damaged_class_index=3
        )

        nd = y == 5
        mean = probs[0][:, nd[0]].mean(dim=1)
        self.assertLess(
            mean[5].item(), 0.01, "No Damage channel not suppressed"
        )
        self.assertLess(mean[3].item(), 0.01, "Damaged channel not suppressed")
        self.assertLess(mean[0].item(), 0.01, "nodata channel not suppressed")
        # Every No Damage pixel must predict a real visual class.
        self.assertTrue(bool(((pred[nd] != 5) & (pred[nd] != 0)).all()))

    def test_allowed_classes_keep_their_mass(self):
        """Excluding three channels must not collapse onto a single class.

        A "No Damage" label says which classes are impossible, not which one
        is right, so the allowed classes should stay roughly interchangeable.
        """
        y = torch.tensor(
            [[[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 5, 5], [5, 5, 5, 5]]]
        )
        probs, _ = _fit_logits(
            y, num_classes=6, no_damage_index=5, damaged_class_index=3
        )

        nd = y == 5
        mean = probs[0][:, nd[0]].mean(dim=1)
        allowed = mean[[1, 2, 4]]
        self.assertGreater(allowed.sum().item(), 0.99)
        # Roughly even, i.e. no arbitrary winner was forced.
        self.assertLess((allowed.max() - allowed.min()).item(), 0.05)

    def test_penalty_increases_with_predicted_damage(self):
        """Higher P(Damaged Building) at No Damage pixels must raise the loss."""
        # One standard Background pixel (1) and one No Damage pixel (4).
        y = torch.tensor([[[1, 4]]])  # shape (1, 1, 2)

        low = torch.zeros(1, 5, 1, 2)
        # Confidently Background at the standard pixel, and low
        # P(Damaged Building) at the No Damage pixel.
        low[0, 1, 0, 0] = 10.0
        low[0, 1, 0, 1] = 10.0

        high = low.clone()
        high[0, 1, 0, 1] = 0.0
        high[0, 3, 0, 1] = 10.0  # high P(Damaged Building) there instead

        loss_low = constraint_segmentation_loss(low, y, no_damage_index=4)
        loss_high = constraint_segmentation_loss(high, y, no_damage_index=4)
        self.assertGreater(loss_high.item(), loss_low.item())

    def test_predicting_no_damage_there_also_raises_the_loss(self):
        """The failure the old form allowed: dumping mass on the No Damage
        channel used to cost nothing."""
        y = torch.tensor([[[1, 4]]])

        good = torch.zeros(1, 5, 1, 2)
        good[0, 1, 0, 0] = 10.0
        good[0, 1, 0, 1] = 10.0  # Background at the No Damage pixel

        leaky = good.clone()
        leaky[0, 1, 0, 1] = 0.0
        leaky[0, 4, 0, 1] = 10.0  # No Damage channel at the No Damage pixel

        self.assertGreater(
            constraint_segmentation_loss(leaky, y, no_damage_index=4).item(),
            constraint_segmentation_loss(good, y, no_damage_index=4).item(),
        )

    def test_no_constraint_pixels_equals_plain_ce(self):
        """With no No Damage pixels the loss is just CE over labeled pixels."""
        torch.manual_seed(2)
        y_hat = torch.randn(1, 5, 3, 3)
        y = torch.tensor([[[0, 1, 2], [3, 1, 2], [2, 3, 1]]])  # no value 4

        got = constraint_segmentation_loss(y_hat, y, no_damage_index=4)
        ce = F.cross_entropy(y_hat, y, ignore_index=0, reduction="none")
        expected = ce[(y > 0) & (y != 4)].mean()
        self.assertTrue(torch.allclose(got, expected))

    def test_all_no_damage_patch_is_finite(self):
        """A patch that is only No Damage (+ unlabeled) must not produce NaN."""
        torch.manual_seed(4)
        y_hat = torch.randn(1, 5, 3, 3, requires_grad=True)
        y = torch.tensor([[[0, 4, 4], [4, 0, 4], [4, 4, 0]]])  # only 0 and 4

        loss = constraint_segmentation_loss(y_hat, y, no_damage_index=4)
        self.assertTrue(torch.isfinite(loss))
        # Loss is purely the constraint term here and must still backprop.
        loss.backward()
        self.assertIsNotNone(y_hat.grad)

    def test_fully_unlabeled_patch_is_finite_zero(self):
        """A patch with no labeled pixels at all yields a finite zero loss."""
        y_hat = torch.randn(1, 5, 2, 2)
        y = torch.zeros(1, 2, 2, dtype=torch.long)  # all unlabeled
        loss = constraint_segmentation_loss(y_hat, y, no_damage_index=4)
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(loss.item(), 0.0)

    def test_degenerate_class_list_does_not_crash(self):
        """No allowed classes left: skip the term rather than log(0)."""
        # Only channels 0..2 with damaged=1 and no-damage=2 leaves nothing.
        y_hat = torch.randn(1, 3, 2, 2, requires_grad=True)
        y = torch.tensor([[[1, 2], [2, 1]]])
        loss = constraint_segmentation_loss(
            y_hat, y, no_damage_index=2, damaged_class_index=1
        )
        self.assertTrue(torch.isfinite(loss))


if __name__ == "__main__":
    unittest.main()
