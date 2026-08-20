# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the "No Damage" constraint loss in ``bda.trainers``.

The regression these guard against is the previous hardcoded class layout
(``y < 4`` / ``y == 4`` / ``probs[:, 3]``), which silently computed the wrong
loss for any project whose class list didn't put "Damaged Building" at index 3
and "No Damage" at index 4 -- and produced a NaN for a patch containing only
"No Damage" and unlabeled pixels.
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


def _reference_loss(y_hat, y, no_damage_index, damaged_class_index):
    """Independent re-implementation used to check the helper."""
    ce = F.cross_entropy(y_hat, y, ignore_index=0, reduction="none")
    standard_mask = (y > 0) & (y != no_damage_index)
    loss = ce[standard_mask].mean()
    constraint_mask = y == no_damage_index
    if constraint_mask.any():
        probs = F.softmax(y_hat, dim=1)
        loss = (
            loss + probs[:, damaged_class_index, :, :][constraint_mask].mean()
        )
    return loss


class TestConstraintSegmentationLoss(unittest.TestCase):
    def test_constraint_fires_for_4_class_layout(self):
        """No Damage == 4 (a class list without a "Cloud" class)."""
        torch.manual_seed(0)
        # num_classes = 5 -> channels 0..4; mask values 0..4, No Damage = 4
        y_hat = torch.randn(1, 5, 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [1, 2, 3, 4], [4, 4, 1, 2], [3, 2, 1, 4]]]
        )

        got = constraint_segmentation_loss(
            y_hat, y, no_damage_index=4, damaged_class_index=3
        )
        self.assertTrue(torch.allclose(got, _reference_loss(y_hat, y, 4, 3)))

    def test_constraint_fires_for_5_class_layout(self):
        """No Damage == 5 (a class list that includes a "Cloud" class).

        This is the case the old hardcoded implementation got wrong: it would
        have treated mask value 4 as "No Damage" and lumped the real value 5
        into the standard cross-entropy term.
        """
        torch.manual_seed(1)
        # num_classes = 6 -> channels 0..5; mask values 0..5, No Damage = 5
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
        """The penalized channel follows damaged_class_index."""
        torch.manual_seed(5)
        y_hat = torch.randn(1, 6, 4, 4)
        y = torch.tensor(
            [[[0, 1, 2, 3], [4, 5, 3, 2], [5, 5, 1, 2], [3, 4, 1, 5]]]
        )

        penalize_3 = constraint_segmentation_loss(
            y_hat, y, no_damage_index=5, damaged_class_index=3
        )
        penalize_4 = constraint_segmentation_loss(
            y_hat, y, no_damage_index=5, damaged_class_index=4
        )
        self.assertFalse(torch.allclose(penalize_3, penalize_4))

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
        # Loss is purely the constraint penalty here and must still backprop.
        loss.backward()
        self.assertIsNotNone(y_hat.grad)

    def test_fully_unlabeled_patch_is_finite_zero(self):
        """A patch with no labeled pixels at all yields a finite zero loss."""
        y_hat = torch.randn(1, 5, 2, 2)
        y = torch.zeros(1, 2, 2, dtype=torch.long)  # all unlabeled
        loss = constraint_segmentation_loss(y_hat, y, no_damage_index=4)
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(loss.item(), 0.0)


if __name__ == "__main__":
    unittest.main()
