#!/usr/bin/env python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Validation script to verify dynamic Overture Maps release resolution works
against the live Azure Blob Storage account.

Usage:
    python -m bda.validate_overture
    # or
    python bda/validate_overture.py
"""

import sys


def main():
    print("=" * 60)
    print("Overture Maps Dynamic Release Validation")
    print("=" * 60)

    # Step 1: Verify fsspec can connect to the blob storage
    print("\n[1/4] Connecting to overturemapswestus2 blob storage...")
    try:
        import fsspec

        t_fs = fsspec.filesystem(
            "az", account_name="overturemapswestus2", anon=True
        )
        print("       OK - connected successfully")
    except Exception as e:
        print(f"       FAIL - could not connect: {e}")
        sys.exit(1)

    # Step 2: List releases and verify we can find valid ones
    print("\n[2/4] Listing available releases...")
    try:
        entries = t_fs.ls("release/")
        print(f"       Found {len(entries)} entries under release/")
        for entry in entries:
            print(f"         - {entry}")
    except Exception as e:
        print(f"       FAIL - could not list releases: {e}")
        sys.exit(1)

    # Step 3: Run get_latest_release() and verify it returns a valid version
    print("\n[3/4] Resolving latest release via get_latest_release()...")
    try:
        from hastegeo.core.utils.footprints import (
            FALLBACK_RELEASE,
            get_latest_release,
        )

        # Clear cache to force a fresh lookup
        get_latest_release.cache_clear()
        latest = get_latest_release()
        print(f"       Resolved: {latest}")

        # Verify the resolved version actually exists in the listing
        entries = t_fs.ls("release/")
        available = [e.rstrip("/").split("/")[-1] for e in entries]
        if latest in available:
            print(f"       OK - version '{latest}' confirmed in blob storage")
        else:
            print(
                f"       WARNING - resolved '{latest}' not found in listing: {available}"
            )
            print(f"       (fallback is {FALLBACK_RELEASE})")
    except Exception as e:
        print(f"       FAIL - get_latest_release() raised: {e}")
        sys.exit(1)

    # Step 4: Verify the resolved path actually exists in blob storage
    print("\n[4/4] Verifying dataset path exists for 'building' type...")
    try:
        from hastegeo.core.utils.footprints import _dataset_path

        path = _dataset_path("building")
        print(f"       Path: {path}")
        contents = t_fs.ls(path)
        file_count = len(contents)
        if file_count > 0:
            print(f"       OK - path exists with {file_count} entries")
        else:
            print("       WARNING - path exists but is empty")
    except FileNotFoundError:
        print("       FAIL - path does not exist in blob storage")
        sys.exit(1)
    except Exception as e:
        print(f"       FAIL - error checking path: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("PASSED - Dynamic Overture release resolution is working")
    print("=" * 60)


if __name__ == "__main__":
    main()
