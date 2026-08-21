# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Custom torchgeo trainers."""

from typing import Any, Optional

import kornia.augmentation as K
import torch
import torch.nn.functional as F
from lightning.pytorch.callbacks import Callback
from torch import Tensor
from torchgeo.trainers import SemanticSegmentationTask


def constraint_segmentation_loss(
    y_hat: Tensor,
    y: Tensor,
    no_damage_index: int,
    damaged_class_index: int = 3,
    ignore_index: int = 0,
) -> Tensor:
    """Constraint loss for weakly-supervised "No Damage" labels.

    Standard cross-entropy is applied to every labeled pixel *except* those of
    the "No Damage" class. At a "No Damage" pixel we don't know the true class
    -- only that the building is *not* damaged -- so instead of a hard label
    we apply a partial-label term over the classes that remain possible.

    "No Damage" is a statement about a building, not something visible in the
    imagery, so it is never a legitimate *output*. At a "No Damage" pixel the
    true class is one of the remaining visual classes: everything except
    "Damaged Building", the "No Damage" channel itself, and the unlabeled /
    nodata channel. Maximizing the total probability of that allowed set --
    ``-log sum_{c in allowed} p_c`` -- pushes all three excluded channels
    toward zero while leaving the choice among the allowed ones free, which is
    exactly the supervision a "No Damage" label carries.

    An earlier form penalized only ``p(Damaged Building)`` here. That is
    under-constrained: it leaves every other channel untouched, so the
    cheapest way to satisfy it is to dump probability on the unsupervised
    "No Damage" channel, and the model duly learns to emit "No Damage" as a
    predicted class. Optimizing raw logits against that objective leaves the
    remaining channels at a dead-even split rather than favoring a real class.

    Args:
        y_hat: Predicted logits of shape ``(N, C, H, W)``.
        y: Integer mask of shape ``(N, H, W)``; 0 is the unlabeled/ignored
            class.
        no_damage_index: Mask value of the "No Damage" class. This equals
            ``labels.classes.index("No Damage") + 1`` and therefore depends on
            the project's class list, so it must be passed in rather than
            hardcoded.
        damaged_class_index: Output channel / mask value of the "Damaged
            Building" class, which a "No Damage" pixel cannot be.
        ignore_index: Channel reserved for unlabeled pixels; never a valid
            prediction.

    Returns:
        The scalar loss.
    """
    ce_loss = F.cross_entropy(
        y_hat, y, ignore_index=ignore_index, reduction="none"
    )
    standard_mask = (y > 0) & (y != no_damage_index)
    if standard_mask.any():
        loss = ce_loss[standard_mask].mean()
    else:
        # No "standard" labeled pixels in this batch (e.g. a patch that is
        # entirely "No Damage" + unlabeled). Avoid a NaN from mean() over an
        # empty tensor while staying attached to the autograd graph.
        loss = y_hat.sum() * 0.0

    constraint_mask = y == no_damage_index
    if constraint_mask.any():
        excluded = {ignore_index, damaged_class_index, no_damage_index}
        allowed = [c for c in range(y_hat.shape[1]) if c not in excluded]
        if allowed:
            # log-sum-exp over the allowed channels' log-probabilities is
            # log(sum p_c) computed stably.
            log_probs = F.log_softmax(y_hat, dim=1)
            allowed_logp = torch.logsumexp(log_probs[:, allowed], dim=1)
            loss = loss + (-allowed_logp)[constraint_mask].mean()

    return loss


class CustomSemanticSegmentationTask(SemanticSegmentationTask):
    """A custom trainer for semantic segmentation tasks."""

    def __init__(
        self,
        *args,
        use_constraint_loss: bool = False,
        no_damage_index: Optional[int] = None,
        damaged_class_index: int = 3,
        **kwargs,
    ):
        if "ignore" in kwargs:
            del kwargs[
                "ignore"
            ]  # workaround for https://github.com/microsoft/torchgeo/pull/2314, can be removed with torchgeo 0.7
        super().__init__(*args, **kwargs)

        self.use_constraint_loss = use_constraint_loss
        # Mask value of the "No Damage" class for the constraint loss. Mask
        # values are (index in labels.classes) + 1, so this depends on the
        # project's class list and is passed in by fine_tune.py rather than
        # hardcoded.
        self.no_damage_index = no_damage_index
        # Output channel / mask value of the "Damaged Building" class, which
        # a "No Damage" pixel is known not to be.
        self.damaged_class_index = damaged_class_index

        self.train_augs = K.AugmentationSequential(
            K.RandomRotation(p=0.5, degrees=90),
            K.RandomHorizontalFlip(p=0.5),
            K.RandomVerticalFlip(p=0.5),
            data_keys=None,
            keepdim=True,
        )

    def configure_callbacks(self) -> list[Callback]:
        """Configures the callbacks for the trainer.

        Returns:
            an empty list to override the default callbacks, we set these in the Trainer
        """
        return []

    def training_step(
        self, batch: Any, batch_idx: int, dataloader_idx: int = 0
    ) -> Tensor:
        """Compute the training loss and additional metrics.

        Args:
            batch: The output of your DataLoader.
            batch_idx: Integer displaying index of this batch.
            dataloader_idx: Index of the current dataloader.

        Returns:
            The loss tensor.
        """
        batch = self.train_augs(batch)
        x = batch["image"]
        y = batch["mask"]

        batch_size = x.shape[0]
        y_hat = self(x)

        if self.use_constraint_loss:
            if self.no_damage_index is None:
                raise ValueError(
                    "use_constraint_loss is True but no_damage_index is not"
                    " set. Pass the mask value of the 'No Damage' class (see"
                    " fine_tune.py)."
                )
            loss = constraint_segmentation_loss(
                y_hat, y, self.no_damage_index, self.damaged_class_index
            )
        else:
            loss = self.criterion(y_hat, y)

        self.log("train_loss", loss, batch_size=batch_size)
        self.train_metrics(y_hat, y)
        self.log_dict(self.train_metrics, batch_size=batch_size)
        return loss
