# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Methods to handle the parsing and merging of command line and YAML file arguments."""

import argparse
import re
from typing import Callable, Optional, Sequence, Union

import yaml

NULLABLE_STR = (str, type(None))
NULLABLE_NUMBER = (int, float, type(None))

_DEFAULT_CONFIG = {
    "experiment_name": str,
    "experiment_dir": str,
    "imagery": {
        "raw_fn": str,
        "num_channels": int,
        "normalization_means": list,
        "normalization_stds": list,
    },
    "labels": {
        "fn": str,
        "classes": list,
        "buffer_in_meters": int,
        "class_to_buffer": str,
        "class_to_buffer_by": str,
    },
    "training": {
        "learning_rate": float,
        "max_epochs": int,
        "batch_size": int,
        "gpu_id": int,
        "log_dir": str,
        "checkpoint_subdir": str,
        "use_constraint_loss": bool,
        "initial_weights_fn": NULLABLE_STR,
    },
    "inference": {
        "output_subdir": str,
        "batch_size": int,
        "gpu_id": int,
        "checkpoint_fn": str,
    },
}

# Keys that are validated only when present. Unlike `_DEFAULT_CONFIG`, a
# missing key here is not an error -- these are opt-in features, and configs
# written before they existed must keep working unchanged.
_OPTIONAL_CONFIG = {
    "labels": {
        "cluster_size_in_meters": NULLABLE_NUMBER,
        "min_pixels_per_cluster": (int, type(None)),
    },
    "training": {
        "gpu_ids": (list, type(None)),
        "preload": (bool, type(None)),
    },
}


def normalize_gpu_ids(
    gpu_ids: Optional[Union[Sequence[int], str, int]] = None,
    gpu_id: Optional[int] = None,
) -> list[int]:
    """Normalize a GPU specification into an ordered, de-duplicated list of ids.

    Precedence: an explicit ``gpu_ids`` (list/tuple, or a comma/space separated
    string) takes priority over a single ``gpu_id``. Returns an empty list when
    neither is provided (i.e. CPU).

    Args:
        gpu_ids: A list/tuple of ints, a comma/space-separated string (e.g.
            ``"0,1,2"``), a single int, or ``None``.
        gpu_id: A single GPU id, used only when ``gpu_ids`` is ``None``.

    Returns:
        Ordered list of unique GPU ids.
    """
    raw: list = []
    if gpu_ids is not None:
        if isinstance(gpu_ids, str):
            raw = gpu_ids.replace(",", " ").split()
        elif isinstance(gpu_ids, int):
            raw = [gpu_ids]
        else:
            raw = list(gpu_ids)
    elif gpu_id is not None:
        raw = [gpu_id]

    ids: list[int] = []
    for item in raw:
        value = int(item)
        if value not in ids:
            ids.append(value)
    return ids


# Mask value / output channel that the rest of the pipeline treats as the
# damaged class. merge_with_building_footprints.py derives the damage fraction
# from this raster value and inference.py assigns it the red palette entry, so
# it is a pipeline-wide contract rather than a free parameter.
DAMAGED_CLASS_INDEX = 3

# Class names the constraint loss looks for. These match the UI's canonical
# picker (ui/src/assets/json/settings.json), but PrimaryClass.name is an
# unconstrained string server-side -- the PutProject docstring's own example
# uses "no_damage" -- so names are matched leniently rather than literally.
NO_DAMAGE_CLASS = "No Damage"
DAMAGED_BUILDING_CLASS = "Damaged Building"


def normalize_class_name(name: str) -> str:
    """Fold a class name to a form that survives casing and separator drift.

    "No Damage", "no_damage", "NO-DAMAGE" and "no  damage" all normalize to
    the same string.

    Args:
        name (str): A class name from the config.

    Returns:
        str: The normalized name.
    """
    return re.sub(r"[\s_\-]+", " ", str(name).strip().casefold())


def find_class_value(classes: Sequence[str], target: str) -> Optional[int]:
    """Return the mask value of `target` in `classes`, or None if absent.

    Mask values are ``index + 1`` because 0 is reserved for "not labeled".
    Matching is via `normalize_class_name`, so casing and separator style
    don't matter.

    Args:
        classes (Sequence[str]): The configured ``labels.classes``.
        target (str): The class name to look for.

    Returns:
        Optional[int]: The mask value, or None when no class matches.
    """
    wanted = normalize_class_name(target)
    for idx, name in enumerate(classes):
        if normalize_class_name(name) == wanted:
            return idx + 1
    return None


def resolve_constraint_indices(
    classes: Sequence[str], use_constraint_loss: bool
) -> tuple:
    """Resolve the mask values the "No Damage" constraint loss operates on.

    Class names are matched with `normalize_class_name`, so casing and
    separator style don't matter -- "No Damage", "no_damage" and "NO-DAMAGE"
    are all accepted. `PrimaryClass.name` is an unconstrained string
    server-side, so the exact spelling a project carries is not guaranteed.

    Mask values are ``classes.index(name) + 1``. The two indices are not
    equally free to move:

    * "No Damage" is read only by the loss, so it can be derived from the
      class list and varies safely.
    * "Damaged Building" is load-bearing for the rest of the pipeline.
      ``merge_with_building_footprints.py`` counts raster value
      ``DAMAGED_CLASS_INDEX`` to compute the damage fraction and
      ``inference.py`` paints it red. Training against a different channel
      while those still read 3 would report a damage fraction of zero (or one
      taken from another class) with no error anywhere.

    So "No Damage" is derived and "Damaged Building" is required to be where
    the downstream steps expect it.

    Args:
        classes (Sequence[str]): The configured ``labels.classes``.
        use_constraint_loss (bool): Whether the constraint loss is enabled.

    Returns:
        tuple: ``(no_damage_index, damaged_class_index)``. The first is None
            when the constraint loss is off.

    Raises:
        ValueError: If the constraint loss is on but the class list can't
            support it.
    """
    if not use_constraint_loss:
        return None, DAMAGED_CLASS_INDEX

    no_damage_index = find_class_value(classes, NO_DAMAGE_CLASS)
    damaged_class_index = find_class_value(classes, DAMAGED_BUILDING_CLASS)

    missing = [
        name
        for name, value in (
            (NO_DAMAGE_CLASS, no_damage_index),
            (DAMAGED_BUILDING_CLASS, damaged_class_index),
        )
        if value is None
    ]
    if missing:
        raise ValueError(
            "training.use_constraint_loss is true but labels.classes is "
            f"missing {missing}. The constraint loss penalizes "
            f"'{DAMAGED_BUILDING_CLASS}' probability at '{NO_DAMAGE_CLASS}' "
            "pixels, so both classes are required. Matching ignores case and "
            f"separators, so e.g. 'no_damage' also works. Got: {list(classes)}"
        )

    if no_damage_index != len(classes):
        raise ValueError(
            f"training.use_constraint_loss is true but '{NO_DAMAGE_CLASS}' is "
            f"entry {no_damage_index} of {len(classes)} in labels.classes; it "
            "must be the LAST one. It is a weak annotation rather than a class "
            "the model predicts, so it is given no output channel at all, "
            "which only works when it is the final mask value. Move it to the "
            f"end of labels.classes. Got: {list(classes)}"
        )

    if damaged_class_index != DAMAGED_CLASS_INDEX:
        raise ValueError(
            f"training.use_constraint_loss is true but "
            f"'{DAMAGED_BUILDING_CLASS}' is class value "
            f"{damaged_class_index} in labels.classes (expected "
            f"{DAMAGED_CLASS_INDEX}). Downstream steps hardcode "
            f"{DAMAGED_CLASS_INDEX} as the damaged class -- "
            "merge_with_building_footprints.py computes the damage fraction "
            "from it and inference.py colors it red -- so training against a "
            "different channel would silently report no damage. Reorder "
            f"labels.classes so '{DAMAGED_BUILDING_CLASS}' is entry "
            f"{DAMAGED_CLASS_INDEX} (1-based), or leave use_constraint_loss "
            f"off. Got: {list(classes)}"
        )

    return no_damage_index, damaged_class_index


def _get_base_parser(description: Optional[str]) -> argparse.ArgumentParser:
    """The base argument parser for all scripts.

    Args:
        description (Optional[str]): The description of the script.

    Returns:
        argparse.ArgumentParser: The argument parser.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config", type=str, required=True, help="Path to config file"
    )
    return parser


def _validate_config(config: dict, template: dict = _DEFAULT_CONFIG) -> None:
    """Checks that a loaded config file is valid.

    Args:
        config (dict): The configuration dictionary to validate.

    Raises:
        KeyError: If a key is missing from the config file.
        TypeError: If a value is not of the expected type.
    """
    for key, value in template.items():
        if key not in config:
            raise KeyError(
                f"Key '{key}' expected, but not found in config file."
            )

        if isinstance(value, dict):
            _validate_config(config[key], value)
        elif not isinstance(config[key], value):
            raise TypeError(
                f"Key '{key}' is not of type '{value}' (value of '{config[key]}'"
                + " found)."
            )


def _validate_optional_values(config: dict) -> None:
    """Range-checks the optional config values that are present.

    Type checks alone let nonsense through to the grid logic: a cluster size
    of 0 makes ``np.arange`` raise ZeroDivisionError, a negative one produces
    no cells at all, and a negative pixel minimum quietly disables culling.
    Hand-edited YAML is the only way to reach these keys today, so catch it
    here where the message can name the key.

    Args:
        config (dict): The configuration dictionary to validate.

    Raises:
        ValueError: If a value is present but out of range.
    """
    cluster_size = config.get("labels", {}).get("cluster_size_in_meters")
    if cluster_size is not None and cluster_size <= 0:
        raise ValueError(
            "labels.cluster_size_in_meters must be greater than 0 (got"
            f" {cluster_size}). Remove the key or set it to null to disable"
            " clustering."
        )

    min_pixels = config.get("labels", {}).get("min_pixels_per_cluster")
    if min_pixels is not None and min_pixels < 0:
        raise ValueError(
            "labels.min_pixels_per_cluster must be 0 or greater (got"
            f" {min_pixels}). Use 0 to keep every cluster."
        )

    gpu_ids = config.get("training", {}).get("gpu_ids")
    if gpu_ids is not None:
        if any(not isinstance(g, int) or g < 0 for g in gpu_ids):
            raise ValueError(
                f"training.gpu_ids must be non-negative integers (got"
                f" {gpu_ids})."
            )


def _validate_optional_config(
    config: dict, template: dict = _OPTIONAL_CONFIG
) -> None:
    """Type-checks the optional config keys that are present.

    Args:
        config (dict): The configuration dictionary to validate.

    Raises:
        TypeError: If a value is present but not of the expected type.
    """
    for key, value in template.items():
        if key not in config:
            continue

        if isinstance(value, dict):
            _validate_optional_config(config[key], value)
        elif not isinstance(config[key], value):
            raise TypeError(
                f"Key '{key}' is not of type '{value}' (value of '{config[key]}'"
                + " found)."
            )


def _merge_argparse_and_config(config: dict, args: argparse.Namespace) -> dict:
    """Merges the config dictionary loaded by YAML with the argparse namespace.

    Overwrites the values in the config dictionary with any values passed on the
    command line. Note, for nested keys, the command line arguments will have '.' to
    separate the keys, e.g. `--training.learning_rate 0.01`.

    Args:
        config (dict): A configuration dictionary loaded from a YAML file.
        args (argparse.Namespace): Subset of the configuration dictionary loaded
            from the command line.

    Returns:
        dict: The merged configuration dictionary.
    """
    for key, value in vars(args).items():
        if value is not None:
            keys = key.split(".")
            d = config
            for k in keys[:-1]:
                d = d[k]
            d[keys[-1]] = value

    return config


def get_args(
    description: Optional[str], add_extra_parser: Optional[Callable]
) -> dict:
    """Handles the parsing of all arguments for a script.

    Args:
        description (Optional[str]): The description of the script (this is shown when
            `--help` is passed).
        add_extra_parser (Optional[Callable]): A function that adds extra command line
            arguments to the base parser so that a user can override config file values.

    Returns:
        dict: Merged set of arguments from the config file (passed with `--config`) and
            command line.
    """
    parser = _get_base_parser(description=description)
    if add_extra_parser is not None:
        parser = add_extra_parser(parser)
    args = parser.parse_args()

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    config = _merge_argparse_and_config(config, args)
    _validate_config(config)
    _validate_optional_config(config)
    _validate_optional_values(config)
    return config
