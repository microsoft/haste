# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any

import pytest
from hastegeo.core.config import Config
from hastegeo.core.runners import local
from hastegeo.core.runners.local_lifecycle import (
    OWNER_LABEL,
    POLICY_LABEL,
    SLOT_LABEL,
    blob_descriptor,
    execution_key,
)

import docker


def conflict() -> docker.errors.APIError:
    return docker.errors.APIError(
        "name conflict", response=SimpleNamespace(status_code=409)
    )


class WorkerLost(BaseException):
    pass


class FakeContainer:
    def __init__(
        self, engine: "FakeDocker", identifier: str, options: dict
    ) -> None:
        self.engine = engine
        self.id = identifier
        self.name = options["name"]
        self.options = options
        self.labels = options.get("labels", {})
        self.status = "created"
        self.attrs = {"State": {"ExitCode": None}}
        self.starts = 0
        self.stops = 0
        self.finish_during_stop = False

    def start(self) -> None:
        self.starts += 1
        self.status = "running"
        self.engine.peak_running = max(
            self.engine.peak_running, len(self.engine.running())
        )
        if self.engine.lose_start_response:
            self.engine.lose_start_response = False
            raise ConnectionError("start response lost")

    def complete(self, exit_code: int = 0) -> None:
        self.status = "exited"
        self.attrs["State"]["ExitCode"] = exit_code

    def stop(self, timeout: int) -> None:
        assert timeout == 5
        self.stops += 1
        self.complete(0 if self.finish_during_stop else 137)
        if self.finish_during_stop:
            raise conflict()

    def unpause(self) -> None:
        self.status = "running"

    def reload(self) -> None:
        pass

    def logs(self, **kwargs) -> list[bytes]:
        assert kwargs == {
            "stream": True,
            "follow": False,
            "stdout": True,
            "stderr": True,
        }
        return [b"workflow output\n"]

    def wait(self) -> None:
        pytest.fail("Local lifecycle must never wait for container completion")

    def remove(self) -> None:
        assert self.status != "running"
        with self.engine.lock:
            self.engine.items.pop(self.name, None)


class FakeDocker:
    def __init__(self) -> None:
        self.containers = self
        self.lock = Lock()
        self.items: dict[str, FakeContainer] = {}
        self.created: list[FakeContainer] = []
        self.peak_running = 0
        self.lose_create_response = False
        self.lose_start_response = False

    def create(self, image: str, **options) -> FakeContainer:
        with self.lock:
            if options["name"] in self.items:
                raise conflict()
            container = FakeContainer(
                self,
                f"container-{len(self.created)}",
                {**options, "image": image},
            )
            self.items[container.name] = container
            self.created.append(container)
        if (
            self.lose_create_response
            and not {SLOT_LABEL, POLICY_LABEL} & container.labels.keys()
        ):
            self.lose_create_response = False
            raise ConnectionError("create response lost")
        return container

    def get(self, name: str) -> FakeContainer:
        with self.lock:
            for container in self.items.values():
                if name in {container.name, container.id}:
                    return container
        raise docker.errors.NotFound("container missing")

    def running(self) -> list[FakeContainer]:
        return [
            item for item in self.items.values() if item.status == "running"
        ]

    def executions(self) -> list[FakeContainer]:
        return [
            item
            for item in self.created
            if not {SLOT_LABEL, POLICY_LABEL} & item.labels.keys()
        ]


class FakeBlobs:
    account_name = "account"
    url = "https://account.blob.core.windows.net/"
    credential = SimpleNamespace(account_key="unit-test-value")

    def __init__(self) -> None:
        self.inputs: dict[tuple[str, str], bytes] = {}
        self.uploads: dict[tuple[str, str], bytes] = {}
        self.download_count = 0
        self.upload_count = 0
        self.fail_at: int | None = None
        self.crash_at: int | None = None
        self.download_started: Event | None = None
        self.download_release: Event | None = None
        self.upload_started: Event | None = None
        self.upload_release: Event | None = None

    def get_blob_client(self, container: str, name: str) -> Any:
        def download_blob() -> Any:
            self.download_count += 1
            if self.download_started is not None:
                self.download_started.set()
                assert self.download_release.wait(5)
            data = self.inputs[(container, name)]
            return SimpleNamespace(readinto=lambda handle: handle.write(data))

        def upload_blob(handle: Any, overwrite: bool) -> None:
            assert overwrite
            self.upload_count += 1
            if self.upload_started is not None:
                self.upload_started.set()
                assert self.upload_release.wait(5)
            if self.upload_count == self.fail_at:
                raise OSError("upload failed")
            if self.upload_count == self.crash_at:
                raise WorkerLost()
            self.uploads[(container, name)] = handle.read()

        return SimpleNamespace(
            download_blob=download_blob, upload_blob=upload_blob
        )

    def get_container_client(self, container: str) -> Any:
        return SimpleNamespace(
            list_blobs=lambda name_starts_with: [
                SimpleNamespace(name=name)
                for key_container, name in self.inputs
                if key_container == container
                and name.startswith(name_starts_with)
            ]
        )


@pytest.fixture
def setup(tmp_path: Path, mocker) -> SimpleNamespace:
    mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Unit test attempted network access"),
    )
    mocker.patch.dict(
        "os.environ",
        {
            "RUNNER_TYPE": "local",
            "DATA_PATH": str(tmp_path / "metadata"),
            "HASTE_LOCAL_MAX_ACTIVE_TASKS": "1",
            "CLEANUP_CONTAINERS": "1",
            "PRESERVE_LOCAL_TASK_DIRS": "0",
            "HASTE_ENABLE_GPU": "0",
        },
    )
    config = Config()
    engine, blobs = FakeDocker(), FakeBlobs()
    mocker.patch.object(local.docker, "from_env", return_value=engine)
    mocker.patch.object(
        local.BlobServiceClient, "from_connection_string", return_value=blobs
    )

    def new_runner(root: Path | None = None) -> local.LocalRunner:
        mocker.patch.object(local, "TASK_WORK_DIR", root or tmp_path / "tasks")
        return local.LocalRunner(config=config)

    return SimpleNamespace(
        runner=new_runner(),
        new_runner=new_runner,
        engine=engine,
        blobs=blobs,
        config=config,
        root=tmp_path,
    )


def submit(
    runner: local.LocalRunner, task_id: str = "task", **kwargs
) -> tuple[str, str]:
    return runner.add_task(
        job_id="job",
        task_id=task_id,
        image_name="training",
        command="python workflow.py",
        output_prefix=f"project/{task_id}",
        **kwargs,
    )


def resource() -> dict:
    return {
        "config": {
            "http_url": "https://account.blob.core.windows.net/data/config.json?sig=discard-me",
            "file_path": "inputs/config.json",
        }
    }


def test_acceptance_returns_before_staging_or_container_completion(
    setup,
) -> None:
    identity = submit(setup.runner, resource_files_for_upload=resource())
    assert identity == ("job", "task")
    assert setup.blobs.download_count == setup.blobs.upload_count == 0
    assert setup.engine.created == []
    assert setup.runner.get_task_receipt(*identity)["phase"] == "queued"
    assert setup.runner.get_task_status(*identity) == "InProgress"


def test_receipts_never_store_signed_urls_or_config_credentials(setup) -> None:
    submit(setup.runner, resource_files_for_upload=resource())
    contents = next(setup.runner.receipts.root.glob("*.json")).read_text()
    assert "discard-me" not in contents
    assert "?sig=" not in contents
    assert "AccountKey=" not in contents
    assert "unit-test-value" not in contents
    assert '"container": "data"' in contents


@pytest.mark.parametrize(
    "kwargs",
    [
        {"env_vars": {"PASSWORD": "value"}},  # pragma: allowlist secret
        {"env_vars": {"HASTE_LOCAL_SHARED_WORKSPACE": "0"}},
        {"env_vars": {"INPUT_DIR": "https://account/file?sig=value"}},
        {
            "resource_files_for_upload": {
                "input": {
                    "http_url": "https://other.blob.core.windows.net/data/input",
                    "file_path": "input",
                }
            }
        },
        {
            "resource_files_for_upload": {
                "input": {
                    "http_url": "https://account.blob.core.windows.net/data/input",
                    "file_path": "..\\outside",
                }
            }
        },
    ],
)
def test_unsafe_receipt_inputs_are_rejected(setup, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        submit(setup.runner, **kwargs)
    assert setup.engine.created == []
    assert list(setup.runner.receipts.root.glob("*.json")) == []


def test_preparation_is_visible_without_blocking_duplicate_acceptance(
    setup,
) -> None:
    setup.blobs.inputs[("data", "config.json")] = b"{}"
    setup.blobs.download_started, setup.blobs.download_release = (
        Event(),
        Event(),
    )
    identity = submit(setup.runner, resource_files_for_upload=resource())
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(setup.runner.reconcile_task, *identity)
        try:
            assert setup.blobs.download_started.wait(5)
            assert (
                setup.runner.get_task_receipt(*identity)["phase"]
                == "preparing"
            )
            assert setup.runner.get_task_status(*identity) == "InProgress"
            assert (
                submit(
                    setup.new_runner(), resource_files_for_upload=resource()
                )
                == identity
            )
        finally:
            setup.blobs.download_release.set()
        future.result(timeout=5)
    assert setup.runner.get_task_receipt(*identity)["phase"] == "running"
    assert setup.engine.executions()[0].status == "running"


def test_worker_restart_recovers_running_identity_without_starting_again(
    setup,
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    restarted = setup.new_runner()
    assert submit(restarted) == identity
    restarted.reconcile_task(*identity)
    assert len(setup.engine.executions()) == 1
    assert setup.engine.executions()[0].starts == 1
    assert restarted.get_task_receipt(*identity)["phase"] == "running"


@pytest.mark.parametrize(
    "lost_response", ["lose_create_response", "lose_start_response"]
)
def test_restart_after_lost_docker_response_reuses_execution(
    setup, lost_response: str
) -> None:
    identity = submit(setup.runner)
    setattr(setup.engine, lost_response, True)
    with pytest.raises(ConnectionError):
        setup.runner.reconcile_task(*identity)
    setup.new_runner().reconcile_task(*identity)
    assert len(setup.engine.executions()) == 1
    assert setup.engine.executions()[0].starts == 1


def test_completed_execution_is_not_restarted_after_worker_loss(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    container = setup.engine.executions()[0]
    container.complete()
    setup.new_runner().reconcile_task(*identity)
    assert container.starts == 1
    assert setup.runner.get_task_status(*identity) == "Processed"


def test_concurrent_duplicate_submission_creates_one_receipt_and_execution(
    setup,
) -> None:
    other = setup.new_runner()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: submit(other), range(16)))
    assert all(identity == ("job", "task") for identity in results)
    assert len(list(setup.runner.receipts.root.glob("*.json"))) == 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(runner.reconcile_tasks)
            for runner in (setup.runner, other)
        ]
        for future in futures:
            future.result(timeout=5)
    assert len(setup.engine.executions()) == 1


def test_identity_reuse_with_changed_command_fails(setup) -> None:
    submit(setup.runner)
    with pytest.raises(ValueError, match="another request"):
        setup.runner.add_task(
            "job", "task", image_name="training", command="another command"
        )


@pytest.mark.parametrize("limit", [1, 2])
def test_host_admission_bounds_active_work_and_drains_queued_receipts(
    setup, limit: int
) -> None:
    setup.config.local_max_active_tasks = limit
    identities = [submit(setup.runner, f"task-{index}") for index in range(5)]
    setup.runner.reconcile_tasks()
    assert len(setup.engine.running()) == limit
    assert (
        sum(
            setup.runner.get_task_receipt(*identity)["phase"] == "queued"
            for identity in identities
        )
        == 5 - limit
    )
    while setup.engine.running():
        for container in setup.engine.running():
            container.complete()
        setup.new_runner().reconcile_tasks()
    assert setup.engine.peak_running == limit
    assert len(setup.engine.executions()) == 5
    assert all(
        setup.runner.get_task_status(*identity) == "Processed"
        for identity in identities
    )


def test_docker_slots_serialize_different_volume_controllers(setup) -> None:
    first = setup.runner
    second = setup.new_runner(setup.root / "other-volume")
    second.volume = "another-volume"
    identity_one, identity_two = submit(first, "one"), submit(second, "two")
    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in [
            executor.submit(first.reconcile_task, *identity_one),
            executor.submit(second.reconcile_task, *identity_two),
        ]:
            future.result(timeout=5)
    assert len(setup.engine.running()) == 1
    assert setup.engine.peak_running == 1


def test_success_waits_for_required_output_persistence(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    setup.engine.executions()[0].complete()
    setup.blobs.upload_started, setup.blobs.upload_release = Event(), Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(setup.runner.reconcile_task, *identity)
        try:
            assert setup.blobs.upload_started.wait(5)
            receipt = setup.new_runner().get_task_receipt(*identity)
            assert receipt["phase"] == "uploading"
            assert receipt["outputs_persisted"] is False
            assert setup.runner.get_task_status(*identity) == "InProgress"
        finally:
            setup.blobs.upload_release.set()
        future.result(timeout=5)
    assert setup.runner.get_task_status(*identity) == "Processed"
    assert (
        setup.runner.get_task_receipt(*identity)["outputs_persisted"] is True
    )


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_upload_failure_is_explicit_and_cleanup_retains_task_files(
    setup, fail_at: int
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    setup.engine.executions()[0].complete()
    setup.blobs.fail_at = fail_at
    setup.runner.reconcile_task(*identity)
    setup.runner.cleanup_task(*identity)
    task_dir = setup.runner.work_dir / "job" / "task"
    assert task_dir.exists()
    receipt = setup.runner.get_task_receipt(*identity)
    assert receipt["phase"] == "failed"
    assert receipt["outputs_persisted"] is False
    assert "persistence failed" in receipt["error"]
    assert (
        json.loads((task_dir / "status.json").read_bytes())[
            "outputs_persisted"
        ]
        is False
    )


def test_restart_mid_upload_retries_persistence_but_never_compute(
    setup,
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    container = setup.engine.executions()[0]
    container.complete()
    setup.blobs.crash_at = 2
    with pytest.raises(WorkerLost):
        setup.runner.reconcile_task(*identity)
    assert setup.runner.get_task_receipt(*identity)["phase"] == "uploading"
    setup.blobs.crash_at = None
    setup.new_runner().reconcile_task(*identity)
    assert setup.runner.get_task_status(*identity) == "Processed"
    assert container.starts == 1


def test_cleanup_keeps_receipt_and_duplicate_tombstone(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    setup.engine.executions()[0].complete()
    setup.runner.reconcile_task(*identity)
    setup.runner.cleanup_task(*identity)
    assert not (setup.runner.work_dir / "job" / "task").exists()
    assert setup.runner.get_task_status(*identity) == "Processed"
    assert submit(setup.new_runner()) == identity
    setup.runner.reconcile_tasks()
    assert len(setup.engine.executions()) == 1


def test_missing_status_file_never_means_success(setup) -> None:
    directory = setup.runner.work_dir / "job" / "legacy"
    directory.mkdir(parents=True)
    assert setup.runner.get_task_status("job", "legacy") == "Failed"
    (directory / "status.json").write_text(
        '{"state": "completed", "exit_code": 0}'
    )
    assert setup.runner.get_task_status("job", "legacy") == "Failed"
    setup.runner.cleanup_task("job", "legacy")
    assert directory.exists()


def test_missing_started_container_is_failure_not_permission_to_recompute(
    setup,
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    container = setup.engine.executions()[0]
    container.complete()
    container.remove()
    setup.new_runner().reconcile_task(*identity)
    assert setup.runner.get_task_status(*identity) == "Failed"
    assert len(setup.engine.executions()) == 1


def test_cancel_before_submission_prevents_late_launch(setup) -> None:
    assert setup.runner.cancel_task("job", "task")
    assert submit(setup.new_runner()) == ("job", "task")
    setup.runner.reconcile_tasks()
    assert setup.engine.executions() == []
    assert setup.runner.get_task_status("job", "task") == "Cancelled"


def test_cancel_queued_work_does_not_consume_capacity(setup) -> None:
    first, queued = submit(setup.runner, "first"), submit(
        setup.runner, "queued"
    )
    setup.runner.reconcile_tasks()
    setup.runner.cancel_task(*queued)
    setup.runner.reconcile_task(*queued)
    assert len(setup.engine.running()) == 1
    assert setup.runner.get_task_status(*first) == "InProgress"
    assert setup.runner.get_task_status(*queued) == "Cancelled"


def test_cancel_during_staging_prevents_container_start(setup) -> None:
    setup.blobs.inputs[("data", "config.json")] = b"{}"
    setup.blobs.download_started, setup.blobs.download_release = (
        Event(),
        Event(),
    )
    identity = submit(setup.runner, resource_files_for_upload=resource())
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(setup.runner.reconcile_task, *identity)
        try:
            assert setup.blobs.download_started.wait(5)
            assert setup.new_runner().cancel_task(*identity)
        finally:
            setup.blobs.download_release.set()
        future.result(timeout=5)
    assert setup.engine.executions() == []
    assert setup.runner.get_task_status(*identity) == "Cancelled"


@pytest.mark.parametrize("finish_race", [False, True])
def test_cancel_stops_exact_execution_and_handles_finish_race(
    setup, finish_race: bool
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    container = setup.engine.executions()[0]
    container.finish_during_stop = finish_race
    assert setup.new_runner().cancel_task(*identity)
    setup.runner.reconcile_task(*identity)
    assert container.stops == 1
    assert container.status == "exited"
    assert setup.runner.get_task_status(*identity) == "Cancelled"


def test_cancel_during_upload_wins_over_late_success(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    setup.engine.executions()[0].complete()
    setup.blobs.upload_started, setup.blobs.upload_release = Event(), Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(setup.runner.reconcile_task, *identity)
        try:
            assert setup.blobs.upload_started.wait(5)
            setup.new_runner().cancel_task(*identity)
        finally:
            setup.blobs.upload_release.set()
        future.result(timeout=5)
    assert setup.runner.get_task_status(*identity) == "Cancelled"


def test_cancel_after_durable_completion_preserves_completion(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    setup.engine.executions()[0].complete()
    setup.runner.reconcile_task(*identity)
    setup.runner.cancel_task(*identity)
    assert setup.runner.get_task_status(*identity) == "Processed"


def test_cancel_rejects_foreign_container_ownership(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    container = setup.engine.executions()[0]
    container.labels[OWNER_LABEL] = "another-execution"
    with pytest.raises(RuntimeError, match="ownership"):
        setup.runner.cancel_task(*identity)
    assert container.stops == 0
    assert container.status == "running"


def test_staging_failure_retains_evidence_and_does_not_run_container(
    setup,
) -> None:
    identity = submit(setup.runner, resource_files_for_upload=resource())
    setup.runner.reconcile_task(*identity)
    setup.runner.cleanup_task(*identity)
    assert setup.engine.executions() == []
    assert setup.runner.get_task_status(*identity) == "Failed"
    assert (setup.runner.work_dir / "job" / "task").exists()


def test_output_layout_still_strips_outputs_prefix(setup) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    outputs = setup.runner.work_dir / "job" / "task" / "outputs"
    outputs.mkdir()
    (outputs / "result.txt").write_text("result")
    setup.engine.executions()[0].complete()
    setup.runner.reconcile_task(*identity)
    names = [name for _, name in setup.blobs.uploads]
    assert "project/task/result.txt" in names
    assert "project/task/outputs/result.txt" not in names


def test_host_capacity_policy_prevents_mixed_controller_limits(setup) -> None:
    submit(setup.runner, "first")
    setup.runner.reconcile_tasks()
    setup.config.local_max_active_tasks = 2
    identity = submit(setup.new_runner(), "second")
    with pytest.raises(RuntimeError, match="capacity policy differs"):
        setup.runner.reconcile_task(*identity)
    assert len(setup.engine.running()) == 1


def test_cloud_container_named_after_account_is_not_stripped() -> None:
    assert blob_descriptor(
        "https://account.blob.core.windows.net/account/input.tif",
        "account",
        "https://account.blob.core.windows.net/",
        container_only=False,
    ) == ("account", "input.tif")


def test_output_patterns_do_not_upload_staged_inputs(setup) -> None:
    identity = submit(
        setup.runner, file_pattern="$AZ_BATCH_TASK_WORKING_DIR/outputs/*"
    )
    setup.runner.reconcile_task(*identity)
    root = setup.runner.work_dir / "job" / "task"
    (root / "staged").mkdir()
    (root / "staged" / "input.txt").write_text("input")
    (root / "outputs").mkdir()
    (root / "outputs" / "result.txt").write_text("result")
    setup.engine.executions()[0].complete()
    setup.runner.reconcile_task(*identity)
    names = {name for _, name in setup.blobs.uploads}
    assert "project/task/result.txt" in names
    assert "project/task/staged/input.txt" not in names
    assert "project/task/logs/workflow_progress.log" in names


def test_permission_fallback_uses_the_task_image_without_privileges(
    setup, mocker
) -> None:
    identity = submit(setup.runner)
    receipt = setup.runner.receipts.load(execution_key(*identity))
    mocker.patch.object(
        setup.runner, "_permissions_needed", side_effect=[True, False]
    )
    helper = mocker.Mock(return_value=b"")
    setup.engine.run = helper
    setup.runner._prepare_output_permissions(receipt)
    options = helper.call_args.kwargs
    assert helper.call_args.args == (receipt.request.image,)
    assert options["network_disabled"] and options["read_only"]
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert "user" not in options
    assert "device_requests" not in options
    assert options["labels"][OWNER_LABEL] == receipt.key


def test_failed_permission_repair_retains_unpersisted_outputs(
    setup, mocker
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    setup.engine.executions()[0].complete()
    mocker.patch.object(setup.runner, "_permissions_needed", return_value=True)
    setup.engine.run = mocker.Mock(return_value=b"")
    setup.runner.reconcile_task(*identity)
    setup.runner.cleanup_task(*identity)
    assert setup.runner.get_task_status(*identity) == "Failed"
    assert not setup.runner.get_task_receipt(*identity)["outputs_persisted"]
    assert (setup.runner.work_dir / "job" / "task").exists()


def test_packaging_staging_links_are_not_persisted_as_outputs(setup) -> None:
    identity = submit(setup.runner, file_pattern="outputs/*")
    root = setup.runner.work_dir / "job" / "task"
    (root / "staged").mkdir()
    try:
        (root / "merged").symlink_to(root / "staged", target_is_directory=True)
    except OSError as error:
        if os.name != "nt" or error.winerror != 1314:
            raise
        pytest.skip("Windows symlink privilege is unavailable")
    setup.runner.reconcile_task(*identity)
    (root / "outputs").mkdir()
    (root / "outputs" / "artifacts.zip").write_bytes(b"archive")
    setup.engine.executions()[0].complete()
    setup.runner.reconcile_task(*identity)
    assert setup.runner.get_task_receipt(*identity)["outputs_persisted"]


def test_receipt_timer_retries_interrupted_cancellation_without_a_queue_worker(
    setup, mocker
) -> None:
    identity = submit(setup.runner)
    setup.runner.reconcile_task(*identity)
    container = setup.engine.executions()[0]
    stop = mocker.patch.object(
        container, "stop", side_effect=ConnectionError("stop response lost")
    )
    with pytest.raises(ConnectionError):
        setup.runner.cancel_task(*identity)
    assert setup.runner.get_task_receipt(*identity)["cancel_requested"]
    stop.side_effect = lambda timeout: container.complete(137)
    setup.new_runner().reconcile_tasks()
    assert setup.runner.get_task_status(*identity) == "Cancelled"
    assert container.status == "exited"


def test_cancel_does_not_stop_another_active_execution(setup) -> None:
    setup.config.local_max_active_tasks = 2
    first = submit(setup.runner, "one")
    second = submit(setup.runner, "two")
    setup.runner.reconcile_tasks()
    setup.runner.cancel_task(*first)
    assert len(setup.engine.running()) == 1
    assert setup.runner.get_task_receipt(*second)["phase"] == "running"
    assert setup.engine.running()[0].stops == 0


def test_legacy_files_prevent_unsafe_recreation_or_status_only_cancellation(
    setup,
) -> None:
    directory = setup.runner.work_dir / "job" / "task"
    directory.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="unknown compute"):
        submit(setup.runner)
    with pytest.raises(RuntimeError, match="legacy"):
        setup.runner.cancel_task("job", "task")
    assert setup.engine.created == []


def test_restart_cannot_silently_change_the_receipts_storage_account(
    setup,
) -> None:
    identity = submit(setup.runner)
    setup.blobs.account_name = "different-account"
    with pytest.raises(RuntimeError, match="storage account changed"):
        setup.new_runner().reconcile_task(*identity)
    assert setup.engine.executions() == []
