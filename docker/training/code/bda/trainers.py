# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Custom torchgeo trainers."""

from typing import Any, Optional

import kornia.augmentation as K
import torch
import torch.nn.functional as F
from lightning.pytorch.callbacks import Callback
from torch import Tensor
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torchgeo.trainers import SemanticSegmentationTask


def channels_last_if_cuda(x: Tensor) -> Tensor:
    """Return a 4-D CUDA tensor in channels-last (NHWC) memory format.

    ``fine_tune.py`` converts the model to channels-last so its convolutions
    run on tensor cores without layout transposes; feeding it NCHW inputs
    would put a transpose back in front of the first convolution of every
    step. CPU tensors and tensors that are not 4-D are returned unchanged, so
    CPU training behaves exactly as before.

    Args:
        x: An input batch.

    Returns:
        ``x`` in channels-last format when it is a 4-D CUDA tensor, otherwise
        ``x`` itself.
    """
    if x.is_cuda and x.dim() == 4:
        return x.contiguous(memory_format=torch.channels_last)
    return x


def maybe_channels_last(
    model: torch.nn.Module, use_cuda: bool
) -> torch.nn.Module:
    """Convert ``model`` to channels-last (NHWC) weights when it runs on CUDA.

    Channels-last weights let cuDNN run the convolutions on tensor cores
    without layout transposes. The conversion is layout-only on the GPU, but
    on CPU it changes the weight strides and so the summation order of the
    convolutions (about 6e-6 in the logits), and gains nothing. The caller
    passes whether CUDA is in use so the decision is made in one place and
    CPU weights stay NCHW-contiguous.

    Args:
        model: The network whose parameters and buffers to convert.
        use_cuda: Whether the model will run on a CUDA device.

    Returns:
        ``model`` in channels-last format when ``use_cuda`` is true, otherwise
        ``model`` untouched.
    """
    if use_cuda:
        return model.to(memory_format=torch.channels_last)
    return model


def fused_adamw_supported(params: list[Tensor]) -> bool:
    """Return whether every parameter can be stepped by the fused AdamW kernel.

    PyTorch's fused AdamW implementation requires every parameter to be a
    floating-point CUDA tensor (it raises otherwise), so this is the exact
    precondition rather than a device heuristic.

    Args:
        params: The parameters the optimizer will own.

    Returns:
        ``True`` when the fused kernel can be used, ``False`` on CPU, for an
        empty parameter list, or when any parameter is non-floating.
    """
    return bool(params) and all(
        p.is_cuda and torch.is_floating_point(p) for p in params
    )


def supervised_logits(y_hat: Tensor, no_damage_index: int) -> Tensor:
    """Return only the logits for classes that receive supervision.

    Channel 0 is kept in the model output as the "Unlabeled" channel but is
    sliced off here so it never receives a gradient. "No Damage" is a weak
    mask annotation rather than a class the model predicts, so it has no
    output channel at all -- it must be the final mask value, which makes
    ``no_damage_index`` equal to the channel count.

    Args:
        y_hat: Predicted logits of shape ``(N, C, H, W)``.
        no_damage_index: Mask value of the "No Damage" class.

    Returns:
        Logits for the deployable classes, shape ``(N, C - 1, H, W)``.

    Raises:
        ValueError: If the model was built with an output channel for
            "No Damage".
    """
    num_channels = y_hat.shape[1]
    if no_damage_index != num_channels:
        raise ValueError(
            f"no_damage_index ({no_damage_index}) must equal the number of"
            f" output channels ({num_channels}). 'No Damage' is a weak label"
            " that must be the final mask value and carry no output channel"
            " of its own."
        )
    return y_hat[:, 1:]


def constraint_segmentation_loss(
    y_hat: Tensor,
    y: Tensor,
    no_damage_index: int,
    damaged_class_index: int = 3,
) -> Tensor:
    """Return the combined CE and weak-label constraint loss."""
    ce_loss, constraint_loss = constraint_segmentation_loss_components(
        y_hat, y, no_damage_index, damaged_class_index
    )
    return ce_loss + constraint_loss


def constraint_segmentation_loss_components(
    y_hat: Tensor,
    y: Tensor,
    no_damage_index: int,
    damaged_class_index: int = 3,
) -> tuple:
    """Compute the CE and weak-label constraint terms separately.

    Cross-entropy is applied to every labeled pixel *except* those of the
    "No Damage" class. At a "No Damage" pixel we don't know the true class --
    only that the building is *not* damaged -- so instead of a hard label its
    predicted "Damaged Building" probability is penalized.

    Both non-deployable concepts are kept out of the softmax entirely. The
    unlabeled channel is sliced off by :func:`supervised_logits`, and
    "No Damage" has no channel to begin with, so neither can ever be
    predicted and neither can absorb probability mass to cheapen the penalty.
    An earlier form left both in: with the "No Damage" channel unsupervised,
    dumping mass there drove p(Damaged Building) to zero at no cost, and the
    model learned to emit "No Damage" as a predicted class.

    Args:
        y_hat: Predicted logits of shape ``(N, C, H, W)``. Channel 0 is the
            non-deployable "Unlabeled" output and receives no gradient.
        y: Integer mask of shape ``(N, H, W)``; 0 is the unlabeled/ignored
            class.
        no_damage_index: Mask value of the "No Damage" class. This equals
            ``labels.classes.index("No Damage") + 1``, and must equal the
            model's output channel count.
        damaged_class_index: Mask value of the "Damaged Building" class,
            which a "No Damage" pixel is known not to be.

    Returns:
        The ``(cross_entropy_loss, constraint_loss)`` pair.
    """
    logits = supervised_logits(y_hat, no_damage_index)

    # Supervised logits are zero-indexed while deployable mask values start
    # at 1, so shift the targets down. Unlabeled and "No Damage" pixels get a
    # dedicated ignored target rather than a class.
    ce_targets = torch.full_like(y, -100)
    standard_mask = (y > 0) & (y != no_damage_index)
    ce_targets[standard_mask] = y[standard_mask] - 1

    ce_loss = F.cross_entropy(
        logits, ce_targets, ignore_index=-100, reduction="none"
    )
    if standard_mask.any():
        ce_loss = ce_loss[standard_mask].mean()
    else:
        # No "standard" labeled pixels in this batch (e.g. a patch that is
        # entirely "No Damage" + unlabeled). Avoid a NaN from mean() over an
        # empty tensor while staying attached to the autograd graph.
        ce_loss = logits.sum() * 0.0

    constraint_mask = y == no_damage_index
    if constraint_mask.any():
        if not 0 < damaged_class_index < no_damage_index:
            raise ValueError(
                "damaged_class_index must identify a supervised mask class"
                " before no_damage_index"
            )
        probs = F.softmax(logits, dim=1)
        constraint_loss = probs[:, damaged_class_index - 1, :, :][
            constraint_mask
        ].mean()
    else:
        constraint_loss = logits.sum() * 0.0

    return ce_loss, constraint_loss


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

    def _constraint_losses(self, y_hat: Tensor, y: Tensor) -> tuple:
        """Compute and return the CE, constraint, and total losses."""
        if self.no_damage_index is None:
            raise ValueError(
                "use_constraint_loss is True but no_damage_index is not set."
                " Pass the mask value of the 'No Damage' class (see"
                " fine_tune.py)."
            )
        ce_loss, constraint_loss = constraint_segmentation_loss_components(
            y_hat, y, self.no_damage_index, self.damaged_class_index
        )
        return ce_loss, constraint_loss, ce_loss + constraint_loss

    def _constraint_metric_targets(self, y: Tensor) -> Tensor:
        """Fold "No Damage" into the ignored class for metrics.

        The metrics are configured for the model's output channels, and
        "No Damage" has none -- passing its mask value straight through would
        be an out-of-range target.
        """
        metric_targets = y.clone()
        metric_targets[metric_targets == self.no_damage_index] = 0
        return metric_targets

    def _constraint_metric_preds(self, y_hat: Tensor) -> Tensor:
        """Reduce logits to the class indices inference would produce.

        Handing the raw logits to the metrics would argmax over channel 0 as
        well, and that channel gets no gradient -- a stray logit there can win
        and be counted as a prediction the deployed model can never make.
        Reducing to indices here the same way ``inference.py`` does makes the
        reported accuracy measure what actually ships.
        """
        return supervised_logits(y_hat, self.no_damage_index).argmax(dim=1) + 1

    def configure_callbacks(self) -> list[Callback]:
        """Configures the callbacks for the trainer.

        Returns:
            an empty list to override the default callbacks, we set these in the Trainer
        """
        return []

    def configure_optimizers(self) -> Any:
        """Initialize the optimizer and learning rate scheduler.

        Same as torchgeo's ``BaseTask.configure_optimizers`` (AdamW at
        ``hparams["lr"]``, ``ReduceLROnPlateau`` with ``hparams["patience"]``
        monitoring ``self.monitor``), except that on CUDA the optimizer uses
        PyTorch's fused AdamW kernel, which steps every parameter in one
        launch instead of one per tensor. The update is mathematically the
        same; only the kernel differs. On CPU, or whenever a parameter is not
        a floating CUDA tensor, the base behaviour is returned unchanged.

        Returns:
            Optimizer and learning rate scheduler.
        """
        config = super().configure_optimizers()
        params = list(self.parameters())
        if not fused_adamw_supported(params):
            return config

        base_optimizer = config["optimizer"]
        optimizer = AdamW(params, **{**base_optimizer.defaults, "fused": True})
        # Re-create the scheduler against the new optimizer so the dict shape,
        # monitor key and patience match the base implementation exactly.
        scheduler = ReduceLROnPlateau(
            optimizer, patience=self.hparams["patience"]
        )
        return {
            "optimizer": optimizer,
            "lr_scheduler": {"scheduler": scheduler, "monitor": self.monitor},
        }

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
        x = channels_last_if_cuda(batch["image"])
        y = batch["mask"]

        batch_size = x.shape[0]
        y_hat = self(x)

        if self.use_constraint_loss:
            ce_loss, constraint_loss, loss = self._constraint_losses(y_hat, y)
            metric_preds = self._constraint_metric_preds(y_hat)
            metric_targets = self._constraint_metric_targets(y)
            self.log("train_ce_loss", ce_loss, batch_size=batch_size)
            self.log(
                "train_constraint_loss", constraint_loss, batch_size=batch_size
            )
        else:
            loss = self.criterion(y_hat, y)
            metric_preds, metric_targets = y_hat, y

        self.log("train_loss", loss, batch_size=batch_size)
        self.train_metrics(metric_preds, metric_targets)
        # NOTE: kept deliberately, unlike upstream, which dropped this line.
        # hastegeo's tbparser reads `train_MulticlassAccuracy` out of the
        # TensorBoard events to build the model's reported metrics, and
        # without this the tag is never written.
        self.log_dict(self.train_metrics, batch_size=batch_size)
        return loss

    def validation_step(
        self, batch: Any, batch_idx: int, dataloader_idx: int = 0
    ) -> None:
        """Compute the validation loss with the same weak-label semantics.

        The base implementation would hand "No Damage" targets straight to a
        criterion whose output has no channel for them, so it has to be
        overridden whenever the constraint loss is in use.

        Args:
            batch: The output of your DataLoader.
            batch_idx: Integer displaying index of this batch.
            dataloader_idx: Index of the current dataloader.
        """
        batch["image"] = channels_last_if_cuda(batch["image"])
        if not self.use_constraint_loss:
            return super().validation_step(batch, batch_idx, dataloader_idx)

        x = batch["image"]
        y = batch["mask"]
        batch_size = x.shape[0]
        y_hat = self(x)

        ce_loss, constraint_loss, loss = self._constraint_losses(y_hat, y)
        self.log("val_ce_loss", ce_loss, batch_size=batch_size)
        self.log("val_constraint_loss", constraint_loss, batch_size=batch_size)
        self.log("val_loss", loss, batch_size=batch_size)
        self.val_metrics(
            self._constraint_metric_preds(y_hat),
            self._constraint_metric_targets(y),
        )
        self.log_dict(self.val_metrics, batch_size=batch_size)

    def test_step(
        self, batch: Any, batch_idx: int, dataloader_idx: int = 0
    ) -> None:
        """Compute the test loss with the same weak-label semantics.

        Args:
            batch: The output of your DataLoader.
            batch_idx: Integer displaying index of this batch.
            dataloader_idx: Index of the current dataloader.
        """
        batch["image"] = channels_last_if_cuda(batch["image"])
        if not self.use_constraint_loss:
            return super().test_step(batch, batch_idx, dataloader_idx)

        x = batch["image"]
        y = batch["mask"]
        batch_size = x.shape[0]
        y_hat = self(x)

        ce_loss, constraint_loss, loss = self._constraint_losses(y_hat, y)
        self.log("test_ce_loss", ce_loss, batch_size=batch_size)
        self.log(
            "test_constraint_loss", constraint_loss, batch_size=batch_size
        )
        self.log("test_loss", loss, batch_size=batch_size)
        self.test_metrics(
            self._constraint_metric_preds(y_hat),
            self._constraint_metric_targets(y),
        )
        self.log_dict(self.test_metrics, batch_size=batch_size)
