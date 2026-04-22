#!/usr/bin/env python3
"""
Startup script to regenerate project stats cache.
This ensures the UI can display projects after container restarts.
"""
import sys
import time


def wait_for_azurite(max_retries=30):
    """Wait for azurite to be ready"""
    import os

    from azure.storage.blob import BlobServiceClient

    conn_str = os.getenv("BLOB_CONNECTION_STRING")
    if not conn_str:
        print("No BLOB_CONNECTION_STRING found, skipping azurite wait")
        return True

    for i in range(max_retries):
        try:
            client = BlobServiceClient.from_connection_string(conn_str)
            client.list_containers()
            print("✓ Azurite is ready")
            return True
        except Exception as e:
            if i < max_retries - 1:
                print(f"Waiting for azurite... ({i+1}/{max_retries})")
                time.sleep(2)
            else:
                print(
                    f"✗ Failed to connect to azurite after {max_retries} attempts: {e}"
                )
                return False
    return False


def regenerate_stats():
    """Regenerate project stats cache from metadata"""
    try:
        from hastegeo.core.config import Config
        from hastegeo.core.processors.metadata import MetadataProcessor

        config = Config()
        project_processor = MetadataProcessor(
            data_type=config.get_metadata_types().PROJECT.value
        )

        print("Regenerating project stats cache...")
        all_projects = []

        try:
            all_data = project_processor.load_all()
            for data in all_data:
                if (
                    isinstance(data, dict)
                    and "projectId" in data
                    and data.get("projectId") != "stats"
                ):
                    all_projects.append(data)

            stats = {
                "projects": all_projects,
                "project_count": len(all_projects),
            }

            project_processor.save("stats", stats)
            print(
                f"✓ Stats cache regenerated successfully ({len(all_projects)} projects)"
            )
            return True

        except FileNotFoundError:
            # No projects yet, create empty stats
            stats = {"projects": [], "project_count": 0}
            project_processor.save("stats", stats)
            print("✓ Initialized empty stats cache (no projects found)")
            return True

    except Exception as e:
        print(f"✗ Error regenerating stats: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("HASTE Startup Initialization")
    print("=" * 50)

    if not wait_for_azurite():
        print("Warning: Azurite not ready, stats regeneration may fail")

    if regenerate_stats():
        print("=" * 50)
        print("✓ Initialization complete")
        print("=" * 50)
        sys.exit(0)
    else:
        print("=" * 50)
        print("✗ Initialization failed")
        print("=" * 50)
        sys.exit(1)
