# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os

from azure.storage.blob import BlobServiceClient
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "haste_build"
    """Custom build hook to bump the package version and copy the built wheel
    to the required directories."""

    def get_plugin_name(self) -> str:
        """Return the name of the plugin."""
        return self.PLUGIN_NAME

    def get_plugin_type(self) -> str:
        """Return the type of the plugin."""
        return "haste_hook"

    def get_plugin_description(self) -> str:
        """Return the description of the plugin."""
        return "Custom build hook to handle special build steps."

    def get_plugin_author(self) -> str:
        """Return the author of the plugin."""
        return "Meygha Machado"

    def get_plugin_license(self) -> str:
        """Return the license of the plugin."""
        return "MIT"

    def upload_to_blob_storage(self, file_path: str, blob_name: str) -> str:
        """Upload file to Azure blob storage and return the URL."""
        try:
            from azure.identity import AzureCliCredential

            # Use AzureCliCredential specifically to match Azure CLI behavior
            credential = AzureCliCredential()
            account_url = "https://researchlabwuopendata.blob.core.windows.net"

            blob_service_client = BlobServiceClient(
                account_url=account_url, credential=credential
            )
            container_name = "haste-binaries"

            # Create blob client
            blob_client = blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )

            # Upload file
            with open(file_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)

            # Return the public URL
            blob_url = f"https://researchlabwuopendata.blob.core.windows.net/{container_name}/{blob_name}"
            print(
                f"Successfully uploaded {blob_name} to blob storage: {blob_url}"
            )
            return blob_url

        except Exception as e:
            print(f"Failed to upload to blob storage: {e}")
            print("Falling back to local file copy...")
            return None

    def initialize(self, version, build_data):
        """Pre build activities"""
        if version == "editable":
            print("Editable build detected. Skipping version bump.")
            return
        major, minor, patch = map(int, self.metadata.version.split("."))
        if os.getenv("HASTE_SKIP_VERSION_BUMP"):
            print("HASTE_SKIP_VERSION_BUMP set, skipping auto-increment.")
            return
        new_version_number = f"{major}.{minor}.{patch + 1}"
        self.metadata._version = new_version_number
        print(f"Bumped package version to: {self.metadata.version}")

    def finalize(self, version, build_data, artifact):
        """Perform actions after the build process."""
        if version == "editable":
            print("Editable build detected. Skipping wheel file updates.")
            return
        version_file_path = os.path.join(
            self.root, "src", "hastegeo", "__about__.py"
        )
        with open(version_file_path, "r") as version_file:
            lines = version_file.readlines()
            for i, line in enumerate(lines):
                if line.startswith("__version__"):
                    lines[i] = f'__version__ = "{self.metadata.version}"\n'
                    break
        with open(version_file_path, "w") as version_file:
            version_file.writelines(lines)

        print(f"Updated version file at {version_file_path}")

        build_dir = "dist"
        wheel_file = None

        # Find the built wheel file
        for file_name in os.listdir(build_dir):
            if file_name.endswith(".whl") and file_name.startswith(
                "hastegeo-"
            ):
                wheel_file = file_name
                break

        if not wheel_file:
            print("No haste wheel file found in build directory!")
            return

        wheel_path = os.path.join(build_dir, wheel_file)

        # Try to upload to blob storage first
        blob_url = self.upload_to_blob_storage(wheel_path, wheel_file)

        # Update the associated requirements.txt files to use the new version.
        # If upload fails, keep existing references unchanged to avoid invalid paths.
        wheel_reference = f"hastegeo @ {blob_url}" if blob_url else None

        if wheel_reference is None:
            print(
                "Blob upload failed; skipping requirements.txt haste reference updates."
            )
            return

        requirements_files = [
            "../api/hastefuncapi/requirements.txt",
            "../api/hastefuncqueues/requirements.txt",
            "../docker/imageryprep/requirements.txt",
        ]

        for requirements_file in requirements_files:
            if not os.path.exists(requirements_file):
                print(f"Requirements file not found: {requirements_file}")
                continue

            with open(requirements_file, "r") as file:
                lines = file.readlines()

            with open(requirements_file, "w") as file:
                for line in lines:
                    if line.strip().startswith("haste") and (
                        "@" in line or "haste-" in line
                    ):
                        # Replace existing haste reference with new blob URL
                        file.write(f"{wheel_reference}\n")
                        print(
                            f"Updated haste reference in {requirements_file}"
                        )
                    else:
                        file.write(line)

        # Update env.yml to also use blob URL for consistency
        env_yml_path = "../env.yml"
        if os.path.exists(env_yml_path):
            with open(env_yml_path, "r") as file:
                lines = file.readlines()

            with open(env_yml_path, "w") as file:
                for line in lines:
                    if "haste" in line and (
                        "@" in line or "haste-" in line and ".whl" in line
                    ):
                        # Use blob URL for env.yml as well for consistency
                        yaml_line = f"    - {wheel_reference}\n"
                        file.write(yaml_line)
                        print(f"Updated haste reference in {env_yml_path}")
                    else:
                        file.write(line)

        print("Cleaning up the build directory")
        os.remove(wheel_path)
        print(f"Removed {wheel_file} from {build_dir}")
