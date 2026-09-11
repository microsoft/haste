# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import hashlib
import json
import re
from contextlib import AbstractContextManager
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..utils.atomic_files import atomic_write, file_lock

Phase = Literal[
    "queued",
    "preparing",
    "running",
    "uploading",
    "completed",
    "failed",
    "cancelled",
]
TERMINAL_PHASES = {"completed", "failed", "cancelled"}
OWNER_LABEL = "org.haste.local.execution"
VOLUME_LABEL = "org.haste.local.volume"
SLOT_LABEL = "org.haste.local.slot"
LIMIT_LABEL = "org.haste.local.limit"
POLICY_LABEL = "org.haste.local.capacity-policy"
SAFE_ENVIRONMENT = {
    "INPUT_DIR",
    "OUTPUT_TRAINING_ZIP_NAME",
    "OUTPUT_INFERENCE_ZIP_NAME",
    "GDAL_TRANSLATE_PARAMS",
    "GDAL_WARP_PARAMS",
    "HASTE_DATALOADER_WORKERS",
    "HASTE_DEBUG_VERBOSE",
    "PYTHONUNBUFFERED",
}


def validate_identity(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("Invalid local job/task identity")
    return value


def execution_key(job_id: str, task_id: str) -> str:
    validate_identity(job_id)
    validate_identity(task_id)
    return hashlib.sha256(f"{job_id}\0{task_id}".encode()).hexdigest()


def safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (
        not parts
        or normalized.startswith("/")
        or any(part in {".", ".."} or ":" in part for part in parts)
        or "\0" in normalized
    ):
        raise ValueError("Task resource paths must be safe relative paths")
    return normalized


def task_path(root: Path, relative: str) -> Path:
    path = root / safe_relative_path(relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Task path escapes its working directory")
    return path


def reject_credentials(value: str) -> str:
    if re.search(
        r"(?i)(AccountKey\s*=|SharedAccessSignature\s*=|"
        r"(?:password|secret|token|sig)\s*=|https?://[^\s]*[?@])",
        value,
    ):
        raise ValueError("Credentials cannot be stored in local receipts")
    return value


def blob_descriptor(
    value: str, account_name: str, account_url: str, *, container_only: bool
) -> tuple[str, str]:
    """Resolve a configured-account URL to a credential-free blob address."""
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Invalid task storage descriptor")
    if parsed.scheme:
        configured = urlsplit(account_url)
        local_hosts = {"localhost", "127.0.0.1", "azurite"}
        same_emulator = (
            parsed.hostname in local_hosts
            and configured.hostname in local_hosts
            and parsed.port == configured.port
        )
        if (
            parsed.scheme not in {"http", "https"}
            or not (parsed.netloc == configured.netloc or same_emulator)
            or (parsed.scheme != "https" and not same_emulator)
        ):
            raise ValueError(
                "Task storage must use the configured Blob account"
            )
        account_parts = [
            part for part in unquote(configured.path).split("/") if part
        ]
    else:
        account_parts = []
    if not parsed.scheme and not container_only:
        raise ValueError(
            "Task blob resources require a configured-account URL"
        )
    parts = unquote(parsed.path).strip("/").split("/")
    if account_parts:
        if parts[: len(account_parts)] != account_parts:
            raise ValueError("Task storage is outside the configured account")
        parts = parts[len(account_parts) :]
    if (
        not parts
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", parts[0])
        or (container_only and len(parts) != 1)
        or (not container_only and len(parts) < 2)
    ):
        raise ValueError("Invalid task blob address")
    blob = "/".join(parts[1:])
    if blob:
        safe_relative_path(blob)
    return parts[0], blob


class ResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container: str
    blob: str
    file_path: str
    prefix: bool = False

    _path = field_validator("file_path")(safe_relative_path)


class LocalTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    storage_account: str
    storage_endpoint: str
    command: str | list[str] | None = None
    arguments: str | list[str] | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    resources: list[ResourceDescriptor] = Field(default_factory=list)
    output_container: str
    output_prefix: str | None = None
    output_patterns: list[str] = Field(default_factory=lambda: ["**/*"])

    @field_validator("output_patterns")
    @classmethod
    def safe_patterns(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Local tasks require an output pattern")
        return [safe_relative_path(pattern) for pattern in value]

    @field_validator("image", "output_prefix", "storage_endpoint")
    @classmethod
    def safe_text(cls, value: str | None) -> str | None:
        return reject_credentials(value) if value is not None else None

    @field_validator("command", "arguments")
    @classmethod
    def safe_command(
        cls, value: str | list[str] | None
    ) -> str | list[str] | None:
        for part in value if isinstance(value, list) else [value]:
            if part is not None:
                reject_credentials(part)
        return value

    @field_validator("environment")
    @classmethod
    def safe_environment(cls, value: dict[str, str]) -> dict[str, str]:
        if value.keys() - SAFE_ENVIRONMENT:
            raise ValueError(
                "Local task environment contains unsupported receipt fields"
            )
        for item in value.values():
            reject_credentials(item)
        return value

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class LocalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    revision: int = 0
    job_id: str
    task_id: str
    accepted_at: float
    request: LocalTaskRequest | None = None
    phase: Phase = "queued"
    slot: int | None = None
    container_id: str | None = None
    start_requested: bool = False
    exit_code: int | None = None
    cancel_requested: bool = False
    outputs_persisted: bool = False
    cleanup_requested: bool = False
    files_cleaned: bool = False
    error: str | None = None

    _identities = field_validator("job_id", "task_id")(validate_identity)

    @property
    def key(self) -> str:
        return execution_key(self.job_id, self.task_id)

    @property
    def container_name(self) -> str:
        return f"haste-local-{self.key}"


class ReceiptStore:
    def __init__(self, work_dir: Path) -> None:
        self.root = work_dir / ".lifecycle"
        self.root.mkdir(parents=True, exist_ok=True)

    def lock(
        self, key: str, *, operation: bool = False, timeout: float = 30
    ) -> AbstractContextManager[None]:
        suffix = "operation" if operation else "receipt"
        return file_lock(self.root / f"{key}.{suffix}.lock", timeout)

    def load(self, key: str) -> LocalReceipt:
        return LocalReceipt.model_validate_json(
            (self.root / f"{key}.json").read_bytes()
        )

    def save(self, receipt: LocalReceipt) -> None:
        receipt.revision += 1
        atomic_write(
            self.root / f"{receipt.key}.json",
            receipt.model_dump_json(indent=2).encode(),
        )

    def list_receipts(self) -> list[LocalReceipt]:
        return sorted(
            (
                LocalReceipt.model_validate_json(path.read_bytes())
                for path in self.root.glob("*.json")
            ),
            key=lambda item: (item.accepted_at, item.key),
        )
