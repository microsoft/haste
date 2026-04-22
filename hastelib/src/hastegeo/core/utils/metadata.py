# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import hashlib
import random
import uuid
from datetime import datetime, timezone


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
