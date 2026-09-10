# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hastegeo.core.utils.local_permissions import (
    prepare_local_task_permissions,
)


class TestLocalPermissions(unittest.TestCase):
    def setUp(self) -> None:
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.task = self.root / "job" / "task"
        self.task.mkdir(parents=True)

    def test_refuses_workspace_root_or_parent_job_directory(self) -> None:
        for path in (self.root, self.task.parent):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prepare_local_task_permissions(
                    path, owner_uid=0, workspace_root=self.root
                )

    def test_never_changes_files_owned_by_another_uid(self) -> None:
        owner = self.task.stat().st_uid
        with patch.object(Path, "chmod") as chmod:
            prepare_local_task_permissions(
                self.task, owner_uid=owner + 1, workspace_root=self.root
            )
        chmod.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits required")
    def test_owned_directories_are_removable_and_files_remain_read_only(
        self,
    ) -> None:
        child = self.task / "checkpoint"
        child.mkdir(mode=0o700)
        weights = child / "weights"
        weights.write_bytes(b"diagnostic")
        weights.chmod(0o600)

        prepare_local_task_permissions(
            self.task, owner_uid=os.getuid(), workspace_root=self.root
        )

        self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o777)
        self.assertEqual(stat.S_IMODE(weights.stat().st_mode), 0o644)

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks required")
    def test_does_not_follow_links_outside_the_task(self) -> None:
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        (self.task / "linked").symlink_to(outside, target_is_directory=True)
        prepare_local_task_permissions(
            self.task, owner_uid=os.getuid(), workspace_root=self.root
        )
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o700)

    @unittest.skipUnless(
        os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0,
        "Root-owned Linux test container required to exercise distinct UIDs",
    )
    def test_worker_outputs_can_be_finalized_by_a_different_uid(self) -> None:
        self.root.chmod(0o777)
        self.task.rmdir()
        self.task.parent.rmdir()
        consumer, producer, shared_group = 1002, 1001, 1001

        def run(code: str, uid: int) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, "-c", code, str(self.root), str(self.task)],
                user=uid,
                group=shared_group,
                capture_output=True,
                text=True,
                check=True,
            )

        run(
            "import sys; from pathlib import Path; "
            "task=Path(sys.argv[2]); task.mkdir(parents=True); task.chmod(0o777)",
            consumer,
        )
        run(
            "import sys; from pathlib import Path; "
            "p=Path(sys.argv[2])/'logs'; p.mkdir(mode=0o700); "
            "f=p/'events'; f.write_text('event'); f.chmod(0o600)",
            producer,
        )
        run(
            "import os,sys; from pathlib import Path; "
            "assert not os.access(Path(sys.argv[2])/'logs', os.W_OK)",
            consumer,
        )
        run(
            "import os,sys; from pathlib import Path; "
            "from hastegeo.core.utils.local_permissions import prepare_local_task_permissions; "
            "prepare_local_task_permissions(Path(sys.argv[2]), "
            "owner_uid=os.getuid(), workspace_root=Path(sys.argv[1]))",
            producer,
        )
        run("import shutil,sys; shutil.rmtree(sys.argv[2])", consumer)
        self.assertFalse(self.task.exists())
