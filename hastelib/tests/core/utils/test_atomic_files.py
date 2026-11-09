# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import subprocess
import sys
from pathlib import Path

import pytest
from hastegeo.core.utils.atomic_files import (
    LockUnavailableError,
    atomic_write,
    file_lock,
)


def test_kernel_lock_is_released_after_owning_process_dies(
    tmp_path: Path,
) -> None:
    path = tmp_path / "operation.lock"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from hastegeo.core.utils.atomic_files import file_lock\n"
        "with file_lock(Path(sys.argv[1])):\n"
        "    print('locked', flush=True)\n"
        "    sys.stdin.read()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(LockUnavailableError):
            with file_lock(path, timeout=0):
                pytest.fail("Competing processes acquired the same lock")
        child.terminate()
        child.wait(timeout=10)
        with file_lock(path, timeout=1):
            pass
    finally:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=10)


def test_failed_atomic_replace_preserves_original_and_removes_temporary_file(
    tmp_path: Path, mocker
) -> None:
    path = tmp_path / "receipt.json"
    atomic_write(path, b"original")
    mocker.patch(
        "hastegeo.core.utils.atomic_files.os.replace",
        side_effect=OSError("replace failed"),
    )
    with pytest.raises(OSError):
        atomic_write(path, b"partial")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]
