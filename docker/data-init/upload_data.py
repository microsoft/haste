#!/usr/bin/env python3
"""
Upload initial data files to Azurite blob storage.
This script waits for Azurite to be ready and then uploads the configuration files.
"""

import os
import time
import sys
from azure.storage.blob import (
    BlobServiceClient,
    CorsRule,
    PublicAccess,
)
from azure.storage.queue import QueueServiceClient
from azure.core.exceptions import ResourceExistsError

# Azurite connection string
CONNECTION_STRING = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;QueueEndpoint=http://azurite:10001/devstoreaccount1;"  # pragma: allowlist secret # gitleaks:allow

def wait_for_azurite(max_retries=30, retry_delay=2):
    """Wait for Azurite to be ready."""
    print("Waiting for Azurite to be ready...")
    
    for attempt in range(max_retries):
        try:
            blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
            # Try to list containers - this will fail if Azurite isn't ready
            list(blob_service_client.list_containers())
            print(f"Azurite is ready after {attempt + 1} attempts")
            return True
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries}: Azurite not ready yet ({e})")
            time.sleep(retry_delay)
    
    print("ERROR: Azurite failed to become ready")
    return False

def create_queues():
    """Create all necessary queues in Azurite."""
    print("Creating queues...")
    queues_to_create = [
        "local-image-queue",
        "local-train-queue",
        "local-stats-queue",
        "local-zip-queue",
        "local-inference-queue",
        "local-embedding-queue",
        "local-prediction-edit-prep-queue",
        "local-image-queue-poison",
        "local-embedding-queue-poison"
    ]
    
    success_count = 0
    try:
        queue_service_client = QueueServiceClient.from_connection_string(CONNECTION_STRING)
        
        for queue_name in queues_to_create:
            try:
                queue_client = queue_service_client.get_queue_client(queue_name)
                queue_client.create_queue()
                print(f"✓ Created queue: {queue_name}")
                success_count += 1
            except ResourceExistsError:
                print(f"Queue already exists: {queue_name}")
                success_count += 1
            except Exception as e:
                print(f"ERROR creating queue {queue_name}: {e}")

    except Exception as e:
        print(f"ERROR connecting to queue service: {e}")
        
    return success_count == len(queues_to_create)

def configure_blob_cors():
    """Allow cross-origin GETs on Azurite blobs from the dev-stack UI.

    The Interactive Labeler fetches PMTiles archives via byte-range HTTP
    requests directly from the browser (pmtiles.js). With the UI on
    localhost:4280 and Azurite on localhost:10000, this is cross-origin
    and gets blocked unless Azurite sends Access-Control-Allow-Origin.

    Azurite respects Blob Service CORS rules set via Set Service Properties,
    so we configure a permissive rule once at data-init time. The same
    config also unblocks any future direct-browser blob reads.
    """
    print("Configuring blob CORS for browser fetches...")
    try:
        bsc = BlobServiceClient.from_connection_string(CONNECTION_STRING)
        bsc.set_service_properties(
            cors=[
                CorsRule(
                    allowed_origins=["*"],
                    allowed_methods=["GET", "HEAD", "OPTIONS"],
                    allowed_headers=["*"],
                    exposed_headers=["*"],
                    max_age_in_seconds=3600,
                )
            ]
        )
        print("✓ Blob CORS configured (allow *)")
        return True
    except Exception as e:
        print(f"ERROR configuring blob CORS: {e}")
        return False


def upload_file_to_blob(container_name, blob_name, file_path):
    """Upload a local file to Azurite as a blob."""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
        
        # Create container if it doesn't exist - with public blob access for local dev
        container_client = blob_service_client.get_container_client(container_name)
        try:
            container_client.create_container(public_access=PublicAccess.Blob)
            print(f"Created container with public blob access: {container_name}")
        except Exception as e:
            if "ContainerAlreadyExists" in str(e):
                print(f"Container already exists: {container_name}")
                # Try to set public access on existing container
                try:
                    container_client.set_container_access_policy(signed_identifiers={}, public_access=PublicAccess.Blob)
                    print(f"Set public blob access on existing container: {container_name}")
                except Exception as access_error:
                    print(f"Note: Could not set public access on existing container: {access_error}")
            else:
                raise e
        
        # Upload the file
        if not os.path.exists(file_path):
            print(f"ERROR: File not found: {file_path}")
            return False
            
        with open(file_path, 'rb') as data:
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(data, overwrite=True)
            print(f"✓ Uploaded {file_path} as {blob_name}")
            return True
            
    except Exception as e:
        print(f"ERROR uploading {file_path}: {e}")
        return False

def main():
    """Main function to upload all data files."""
    print("--- Starting Data Initialization ---")
    
    if not wait_for_azurite():
        sys.exit(1)
        
    print("\n--- Creating Queues ---")
    if not create_queues():
        print("Failed to create all queues. Exiting.")
        sys.exit(1)

    print("\n--- Configuring Blob CORS ---")
    if not configure_blob_cors():
        # Non-fatal: existing data still loads, but the Interactive Labeler's
        # browser-side PMTiles fetch will be CORS-blocked.
        print("Continuing despite CORS configuration failure.")

    print("\n--- Uploading Blob Files ---")
    files_to_upload = [
        ("data", "config_admin_settings.json", "/data/config_admin_settings.json"),
        ("data", "users_acl.json", "/data/users_acl.json"),
        ("data", "project_stats.json", "/data/project_stats.json")
    ]
    
    upload_success_count = 0
    for container, blob, path in files_to_upload:
        if upload_file_to_blob(container, blob, path):
            upload_success_count += 1
            
    if upload_success_count == len(files_to_upload):
        print("\n--- Data Initialization Complete ---")
    else:
        print(f"\n--- Data Initialization Failed: Only {upload_success_count}/{len(files_to_upload)} files uploaded. ---")
        sys.exit(1)

if __name__ == "__main__":
    main()
