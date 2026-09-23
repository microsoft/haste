# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import hashlib
import json
import random
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache

# Job monitors re-queue their whole record, status history included, on every
# poll, and an Azure Storage queue message cannot exceed 64 KiB. Keeping the
# history well under that leaves room for the rest of the record.
MAX_STATUS_MESSAGE_BYTES = 16 * 1024
STATUS_HISTORY_TRIMMED = "Earlier status messages were trimmed"

# append_status_message writes each entry as "\n<ISO-8601 timestamp>: <message>",
# and a message may itself span several lines.
_STATUS_ENTRY_START = re.compile(
    r"\n(?=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?: )"
)


def _serialized_size(text: str) -> int:
    """Return how many bytes ``text`` adds to a queued JSON message.

    Records are queued with ``json.dumps``, which escapes non-ASCII by default,
    so its output is ASCII and its length is the byte count. One character can
    take up to twelve bytes (an escaped surrogate pair).
    """
    return len(json.dumps(text)) - 2


def _longest_fit(text: str, max_bytes: int, keep_end: bool) -> str:
    """Return the longest prefix (or suffix) of ``text`` within ``max_bytes``."""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        part = text[len(text) - mid :] if keep_end else text[:mid]
        if _serialized_size(part) <= max_bytes:
            low = mid
        else:
            high = mid - 1
    return text[len(text) - low :] if keep_end else text[:low]


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
        for known_type in sorted(
            set(_known_metadata_types()) | {data_type}, key=len, reverse=True
        )
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

    @staticmethod
    def upsert_status_message(
        status_message: str,
        message: str,
        replace_prefix: str,
        timestamp: str = None,
    ):
        """Append ``message``, replacing the last entry if it starts with ``replace_prefix``.

        Monitors that report the same kind of progress on every poll use this
        so a long-running job keeps one current progress entry instead of
        adding one per poll.
        """
        status_message = status_message or ""
        entry_starts = [
            match.start()
            for match in _STATUS_ENTRY_START.finditer(status_message)
        ]
        if entry_starts:
            last_entry = status_message[entry_starts[-1] + 1 :]
            _, _, last_message = last_entry.partition(": ")
            if last_message.startswith(replace_prefix):
                status_message = status_message[: entry_starts[-1]]
        return MetadataUtils.append_status_message(
            status_message, message, timestamp=timestamp
        )

    @staticmethod
    def trim_status_message(
        status_message: str, max_bytes: int = MAX_STATUS_MESSAGE_BYTES
    ):
        """Keep the newest whole entries of ``status_message`` within ``max_bytes``.

        The budget is measured as the history's size once serialized into a
        queued JSON message, so escaped non-ASCII text counts at its real
        size. Dropped history is replaced by a single entry saying so, stamped
        with the oldest retained entry's time so the history stays in order.
        """
        if not status_message or (
            _serialized_size(status_message) <= max_bytes
        ):
            return status_message
        entry_starts = [
            match.start()
            for match in _STATUS_ENTRY_START.finditer(status_message)
        ]
        if not entry_starts:
            return _longest_fit(status_message, max_bytes, keep_end=True)
        for start in entry_starts[1:]:
            retained = status_message[start:]
            timestamp = retained[1:].partition(": ")[0]
            marker = f"\n{timestamp}: {STATUS_HISTORY_TRIMMED}"
            if _serialized_size(marker + retained) <= max_bytes:
                return marker + retained
        # Not even the newest entry fits on its own: keep its beginning,
        # which carries its timestamp and the start of its message.
        return _longest_fit(
            status_message[entry_starts[-1] :], max_bytes, keep_end=False
        )
