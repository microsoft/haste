# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import hashlib
import random
import uuid
from datetime import datetime, timezone
from functools import lru_cache


@lru_cache(maxsize=1)
def _known_metadata_types() -> tuple[str, ...]:
    from ..config import Config

    return tuple(
        sorted(
            (
                metadata_type.value
                for metadata_type in Config.get_metadata_types()
            ),
            key=len,
            reverse=True,
        )
    )


def matches_metadata_type(path: str, data_type: str) -> bool:
    """Return whether a stored name belongs to the requested metadata type.

    Existing records use ``{type}_{identifier}``, while some type names are
    prefixes of others (notably ``model`` and ``model_catalog``). Assigning a
    name to the longest known matching type preserves the existing layout
    without allowing broader scans to consume a narrower type.
    """
    name = path.rsplit("/", 1)[-1]
    matching_types = [
        known_type
        for known_type in _known_metadata_types()
        if name.startswith(f"{known_type}_")
    ]
    if not matching_types:
        return name.startswith(f"{data_type}_")
    return matching_types[0] == data_type


class MetadataUtils:
    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    @staticmethod
    def generate_int_id():
        return str(uuid.uuid4().int)

    @staticmethod
    def get_timestamp():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def get_short_date():
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def generate_short_int_id(digits=4):
        return str(random.randint(0, 9999)).zfill(digits)

    @staticmethod
    def hash_string(string: str):
        return hashlib.sha256(string.encode()).hexdigest()

    @staticmethod
    def append_status_message(
        status_message: str, message: str, timestamp: str = None
    ):
        if status_message is None:
            status_message = ""
        timestamp = timestamp if timestamp else MetadataUtils.get_timestamp()
        return status_message + f"\n{timestamp}: {message}"
