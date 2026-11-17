# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Validate package-run provenance before downloading or accessing Azure."""

import argparse
import json
import subprocess

WORKFLOW_PATH = ".github/workflows/gdal-runtime-build.yml"


def deployment_event(
    source_ref: str, environment: str, candidate_dev1: bool
) -> str:
    if source_ref == "refs/heads/main":
        if candidate_dev1:
            raise ValueError(
                "Candidate deployment requires a non-main branch."
            )
        return "push"
    if (
        source_ref.startswith("refs/heads/")
        and environment == "dev1"
        and candidate_dev1
    ):
        return "workflow_dispatch"
    raise ValueError(
        "Non-main deployments require explicit dev1 candidate mode."
    )


def validate_run(
    run: dict,
    *,
    repository: str,
    source_ref: str,
    source_sha: str,
    environment: str,
    candidate_dev1: bool,
) -> None:
    expected_event = deployment_event(source_ref, environment, candidate_dev1)
    expected = {
        "status": "completed",
        "conclusion": "success",
        "path": WORKFLOW_PATH,
        "event": expected_event,
        "head_sha": source_sha,
        "head_branch": source_ref.removeprefix("refs/heads/"),
    }
    if not source_sha or any(
        run.get(field) != value for field, value in expected.items()
    ):
        raise ValueError(
            "Package run does not match the trusted source build."
        )
    if (run.get("head_repository") or {}).get("full_name") != repository:
        raise ValueError("Package source must belong to this repository.")
    if (run.get("repository") or {}).get("full_name") != repository:
        raise ValueError("Package run must belong to this repository.")


def validate_build_evidence(
    jobs: list[dict],
    artifacts: list[dict],
    source_sha: str,
    candidate_dev1: bool,
) -> None:
    job_name = "attest-dev1-candidate" if candidate_dev1 else "attest"
    if not any(
        job.get("name") == job_name and job.get("conclusion") == "success"
        for job in jobs
    ):
        raise ValueError(
            "The required package-attestation job did not succeed."
        )
    if not any(
        artifact.get("name") == f"haste-function-packages-{source_sha}"
        and artifact.get("expired") is False
        for artifact in artifacts
    ):
        raise ValueError(
            "The exact-source package artifact is missing or expired."
        )


def _gh_json(*arguments: str) -> dict | list:
    return json.loads(subprocess.check_output(["gh", *arguments], text=True))


def resolve_run(run_id: str = "", **source: str | bool) -> str:
    event = deployment_event(
        source["source_ref"], source["environment"], source["candidate_dev1"]
    )
    repository = source["repository"]
    if run_id:
        if not run_id.isascii() or not run_id.isdecimal():
            raise ValueError("Package run ID must be numeric.")
        candidates = [run_id]
    else:
        candidates = [
            str(run["databaseId"])
            for run in _gh_json(
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "gdal-runtime-build.yml",
                "--commit",
                source["source_sha"],
                "--event",
                event,
                "--status",
                "success",
                "--limit",
                "20",
                "--json",
                "databaseId",
            )
        ]
    for candidate in candidates:
        endpoint = f"repos/{repository}/actions/runs/{candidate}"
        run = _gh_json("api", endpoint)
        try:
            validate_run(run, **source)
            jobs = _gh_json("api", f"{endpoint}/jobs?per_page=100")["jobs"]
            artifacts = _gh_json("api", f"{endpoint}/artifacts?per_page=100")[
                "artifacts"
            ]
            validate_build_evidence(
                jobs, artifacts, source["source_sha"], source["candidate_dev1"]
            )
        except ValueError:
            if run_id:
                raise
            continue
        return candidate
    raise ValueError(
        "No compatible, attested, unexpired exact-source build exists."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument(
        "--candidate-dev1", choices=("true", "false"), required=True
    )
    parser.add_argument("--check-source-only", action="store_true")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    try:
        candidate = args.candidate_dev1 == "true"
        event = deployment_event(args.source_ref, args.environment, candidate)
        if not args.check_source_only:
            event = resolve_run(
                run_id=args.run_id,
                repository=args.repository,
                source_ref=args.source_ref,
                source_sha=args.source_sha,
                environment=args.environment,
                candidate_dev1=candidate,
            )
    except (ValueError, TypeError) as error:
        parser.exit(1, f"Package provenance rejected: {error}\n")
    except subprocess.CalledProcessError:
        parser.exit(1, "Cannot retrieve trusted package-run metadata.\n")
    print(event)


if __name__ == "__main__":
    main()
