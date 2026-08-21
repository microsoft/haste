# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the "No Damage" constraint loss in ``bda.trainers``.

Three defects are covered.

*Class layout*: the loss used to hardcode ``y == 4`` and ``probs[:, 3]``, so it
computed the wrong objective for any project whose class list didn't put
"Damaged Building" third and "No Damage" fourth.

*Under-constrained objective*: penalizing only ``p(Damaged Building)`` left
every other channel free, so the model could satisfy the loss by predicting the
unsupervised "No Damage" channel. Inference duly emitted that class in dev.

*The structural cause of the above*: "No Damage" had an output channel at all.
It describes a building rather than anything visible in the imagery, so it is
never a legitimate prediction. It now carries no channel, which makes emitting
it impossible rather than merely unattractive. Channel 0 ("Unlabeled") is still
emitted but excluded from the loss, so inference has to drop it too.
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

from bda.trainers import (  # noqa: E402
    constraint_segmentation_loss,
    constraint_segmentation_loss_components,
    supervised_logits,
)

# 1 Background, 2 Building, 3 Damaged Building, 4 No Damage.
# "No Damage" is last and has no channel, so the model emits 4: channel 0
# ("Unlabeled") plus one per deployable class.
FOUR_CLASS = {"num_channels": 4, "no_damage_index": 4, "damaged": 3}
# 1 Background, 2 Building, 3 Damaged Building, 4 Cloud, 5 No Damage.
FIVE_CLASS = {"num_channels": 5, "no_damage_index": 5, "damaged": 3}


def _reference_loss(y_hat, y, no_damage_index, damaged_class_index):
    """Independent re-implementation used to check the helper."""
    logits = y_hat[:, 1:]
    targets = torch.full_like(y, -100)
    standard_mask = (y > 0) & (y != no_damage_index)
    targets[standard_mask] = y[standard_mask] - 1
    ce = F.cross_entropy(logits, targets, ignore_index=-100, reduction="none")
    loss = ce[standard_mask].mean()
    constraint_mask = y == no_damage_index
    if constraint_mask.any():
        probs = F.softmax(logits, dim=1)
        loss = loss + probs[:, damaged_class_index - 1][constraint_mask].mean()
    return loss


def _fit(y, layout, steps=1500):
    """Optimize raw logits against the loss; return softmax and predictions.

    No network in the way, so whatever the objective rewards is what this
    converges to. Predictions follow inference: channel 0 dropped, indices
    shifted back onto the 1-based mask values.
    """
    torch.manual_seed(0)
    logits = torch.zeros(
        1, layout["num_channels"], *y.shape[1:], requires_grad=True
    )
    opt = torch.optim.Adam([logits], lr=0.1)
    for _ in range(steps):
        opt.zero_grad()
        constraint_segmentation_loss(
            logits, y, layout["no_damage_index"], layout["damaged"]
        ).backward()
        opt.step()
    final = logits.detach()
    return F.softmax(final[:, 1:], dim=1), final[:, 1:].argmax(dim=1) + 1


class TestSupervisedLogits(unittest.TestCase):
    """No Damage must be the final mask value with no channel of its own."""

    def test_drops_the_unlabeled_channel(self):
        y_hat = torch.randn(2, 4, 3, 3)
        out = supervised_logits(y_hat, no_damage_index=4)
        self.assertEqual(out.shape[1], 3)
        self.assertTrue(torch.equal(out, y_hat[:, 1:]))

    def test_rejects_a_model_with_a_no_damage_channel(self):
        """num_classes = len(classes) + 1 is the non-constraint layout."""
        y_hat = torch.randn(1, 5, 2, 2)  # one channel too many
        with self.assertRaises(ValueError) as ctx:
            supervised_logits(y_hat, no_damage_index=4)
        self.assertIn("no output channel", str(ctx.exception))

    def test_rejects_no_damage_that_is_not_the_last_class(self):
        y_hat = torch.randn(1, 5, 2, 2)
        with self.assertRaises(ValueError):
            supervised_logits(y_hat, no_damage_index=3)


class TestConstraintSegmentationLoss(unittest.TestCase):
    def test_matches_reference_for_4_class_layout(self):
        torch.manual_seed(0)
        y_hat = torch.randn(1, FOUR_CLASS["num_channels"], 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [1, 2, 3, 4], [4, 4, 1, 2], [3, 2, 1, 4]]]
        )
        got = constraint_segmentation_loss(y_hat, y, 4, 3)
        self.assertTrue(torch.allclose(got, _reference_loss(y_hat, y, 4, 3)))

    def test_matches_reference_for_5_class_layout(self):
        """A "Cloud" class shifts "No Damage" to 5; the old code assumed 4."""
        torch.manual_seed(1)
        y_hat = torch.randn(1, FIVE_CLASS["num_channels"], 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )
        got = constraint_segmentation_loss(y_hat, y, 5, 3)
        self.assertTrue(torch.allclose(got, _reference_loss(y_hat, y, 5, 3)))

    def test_components_sum_to_the_total(self):
        torch.manual_seed(7)
        y_hat = torch.randn(1, FIVE_CLASS["num_channels"], 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )
        ce, constraint = constraint_segmentation_loss_components(
            y_hat, y, 5, 3
        )
        total = constraint_segmentation_loss(y_hat, y, 5, 3)
        self.assertTrue(torch.allclose(ce + constraint, total))
        self.assertGreater(constraint.item(), 0.0)

    def test_damaged_class_index_is_honored(self):
        torch.manual_seed(5)
        y_hat = torch.randn(1, FIVE_CLASS["num_channels"], 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )
        self.assertFalse(
            torch.allclose(
                constraint_segmentation_loss(y_hat, y, 5, 3),
                constraint_segmentation_loss(y_hat, y, 5, 4),
            )
        )

    def test_rejects_a_damaged_index_at_or_after_no_damage(self):
        y_hat = torch.randn(1, FIVE_CLASS["num_channels"], 2, 2)
        y = torch.tensor([[[5, 1], [2, 5]]])
        with self.assertRaises(ValueError):
            constraint_segmentation_loss(y_hat, y, 5, 5)

    # ── What the objective actually produces ────────────────────────────────

    def test_no_damage_can_never_be_predicted(self):
        """The dev report: inference emitting class 5.

        With no channel for it, the class is not merely unattractive -- it is
        unrepresentable. Same for the unsupervised channel 0.
        """
        y = torch.tensor(
            [[[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 5, 5], [5, 5, 5, 5]]]
        )
        _, pred = _fit(y, FIVE_CLASS)

        self.assertGreaterEqual(pred.min().item(), 1)
        self.assertLessEqual(pred.max().item(), 4)
        self.assertFalse(bool((pred == 5).any()))
        self.assertFalse(bool((pred == 0).any()))

    def test_no_damage_pixels_avoid_the_damaged_class(self):
        """What the weak label does say: these buildings are not damaged."""
        y = torch.tensor(
            [[[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 5, 5], [5, 5, 5, 5]]]
        )
        probs, pred = _fit(y, FIVE_CLASS)

        nd = y == 5
        # probs are over supervised channels: index 0 -> mask value 1, etc.
        mean_damaged = probs[0][FIVE_CLASS["damaged"] - 1, nd[0]].mean()
        self.assertLess(mean_damaged.item(), 0.01)
        self.assertFalse(bool((pred[nd] == FIVE_CLASS["damaged"]).any()))

    def test_remaining_classes_stay_interchangeable(self):
        """The label says which class is impossible, not which one is right."""
        y = torch.tensor(
            [[[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 5, 5], [5, 5, 5, 5]]]
        )
        probs, _ = _fit(y, FIVE_CLASS)

        nd = y == 5
        # Mask values 1, 2, 4 -> supervised indices 0, 1, 3.
        allowed = probs[0][:, nd[0]].mean(dim=1)[[0, 1, 3]]
        self.assertGreater(allowed.sum().item(), 0.99)
        self.assertLess((allowed.max() - allowed.min()).item(), 0.05)

    def test_unlabeled_channel_receives_no_gradient(self):
        """Channel 0 is emitted for shape compatibility, never trained."""
        y_hat = torch.randn(
            1, FIVE_CLASS["num_channels"], 3, 3, requires_grad=True
        )
        y = torch.tensor([[[1, 2, 3], [4, 5, 5], [5, 1, 2]]])

        constraint_segmentation_loss(y_hat, y, 5, 3).backward()

        self.assertTrue(bool((y_hat.grad[:, 0] == 0).all()))
        self.assertTrue(bool((y_hat.grad[:, 1:] != 0).any()))

    def test_penalty_increases_with_predicted_damage(self):
        """One Background pixel (1) and one No Damage pixel (4)."""
        y = torch.tensor([[[1, 4]]])

        low = torch.zeros(1, FOUR_CLASS["num_channels"], 1, 2)
        # Channel i corresponds to mask value i.
        low[0, 1, 0, 0] = 10.0  # confidently Background at the labeled pixel
        low[0, 1, 0, 1] = 10.0  # Background at the No Damage pixel

        high = low.clone()
        high[0, 1, 0, 1] = 0.0
        high[0, 3, 0, 1] = 10.0  # Damaged Building there instead

        self.assertGreater(
            constraint_segmentation_loss(high, y, 4, 3).item(),
            constraint_segmentation_loss(low, y, 4, 3).item(),
        )

    def test_no_constraint_pixels_equals_plain_ce(self):
        """With no No Damage pixels the loss is CE over the labeled ones."""
        torch.manual_seed(2)
        y_hat = torch.randn(1, FOUR_CLASS["num_channels"], 3, 3)
        y = torch.tensor([[[0, 1, 2], [3, 1, 2], [2, 3, 1]]])  # no value 4

        got = constraint_segmentation_loss(y_hat, y, 4, 3)

        targets = torch.full_like(y, -100)
        labeled = y > 0
        targets[labeled] = y[labeled] - 1
        ce = F.cross_entropy(
            y_hat[:, 1:], targets, ignore_index=-100, reduction="none"
        )
        self.assertTrue(torch.allclose(got, ce[labeled].mean()))

    def test_all_no_damage_patch_is_finite(self):
        """A patch of only No Damage (+ unlabeled) must not produce NaN."""
        torch.manual_seed(4)
        y_hat = torch.randn(
            1, FOUR_CLASS["num_channels"], 3, 3, requires_grad=True
        )
        y = torch.tensor([[[0, 4, 4], [4, 0, 4], [4, 4, 0]]])

        loss = constraint_segmentation_loss(y_hat, y, 4, 3)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertIsNotNone(y_hat.grad)

    def test_fully_unlabeled_patch_is_finite_zero(self):
        y_hat = torch.randn(1, FOUR_CLASS["num_channels"], 2, 2)
        y = torch.zeros(1, 2, 2, dtype=torch.long)
        loss = constraint_segmentation_loss(y_hat, y, 4, 3)
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(loss.item(), 0.0)


if __name__ == "__main__":
    unittest.main()
