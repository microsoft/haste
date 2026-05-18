# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from typing import Any, Dict, List, Optional

from hastegeo.core.utils.logs import Logger

import docker


class DockerManager:
    """Helper class for Docker container management in local runner."""

    def __init__(self):
        try:
            self.client = docker.from_env()
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Docker daemon: {e}")

        self.logger = Logger.get_logger(__name__)

    def ensure_image_exists(self, image_name: str) -> bool:
        """Check if Docker image exists locally."""
        try:
            self.client.images.get(image_name)
            self.logger.info(f"Docker image {image_name} is available")
            return True
        except docker.errors.ImageNotFound:
            self.logger.warning(f"Docker image {image_name} not found locally")
            return False

    def run_container(
        self,
        image: str,
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        working_dir: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Run a Docker container and return its output."""
        try:
            self.logger.info(
                f"Running container {image} with command: {command}"
            )

            result = self.client.containers.run(
                image,
                command=command,
                environment=environment,
                volumes=volumes,
                working_dir=working_dir,
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
                **kwargs,
            )

            # Handle different types of output
            if isinstance(result, bytes):
                return result.decode("utf-8", errors="replace")
            else:
                return str(result)

        except docker.errors.ContainerError as e:
            self.logger.error(
                f"Container {image} failed with exit code {e.exit_status}"
            )
            self.logger.error(
                f"Container logs: {e.stderr.decode('utf-8', errors='replace') if e.stderr else 'No stderr'}"
            )
            raise
        except docker.errors.ImageNotFound:
            self.logger.error(f"Docker image not found: {image}")
            raise
        except docker.errors.APIError as e:
            self.logger.error(f"Docker API error: {e}")
            raise

    def run_container_async(
        self,
        image: str,
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        working_dir: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs,
    ) -> docker.models.containers.Container:
        """Run a Docker container asynchronously and return the container object."""
        try:
            self.logger.info(
                f"Starting async container {image} with command: {command}"
            )

            container = self.client.containers.run(
                image,
                command=command,
                environment=environment,
                volumes=volumes,
                working_dir=working_dir,
                name=name,
                detach=True,
                stdout=True,
                stderr=True,
                **kwargs,
            )

            self.logger.info(f"Started container {container.short_id}")
            return container

        except docker.errors.ImageNotFound:
            self.logger.error(f"Docker image not found: {image}")
            raise
        except docker.errors.APIError as e:
            self.logger.error(f"Docker API error: {e}")
            raise

    def get_container_logs(
        self, container: docker.models.containers.Container
    ) -> str:
        """Get logs from a container."""
        try:
            logs = container.logs(stdout=True, stderr=True)
            return logs.decode("utf-8", errors="replace")
        except Exception as e:
            self.logger.error(f"Failed to get container logs: {e}")
            return ""

    def wait_for_container(
        self,
        container: docker.models.containers.Container,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Wait for container to finish and return exit status."""
        try:
            result = container.wait(timeout=timeout)
            logs = self.get_container_logs(container)

            return {
                "exit_code": result["StatusCode"],
                "logs": logs,
                "error": result.get("Error", None),
            }
        except Exception as e:
            self.logger.error(f"Error waiting for container: {e}")
            return {
                "exit_code": -1,
                "logs": self.get_container_logs(container),
                "error": str(e),
            }
        finally:
            # Clean up container
            try:
                container.remove()
            except Exception as cleanup_err:
                self.logger.debug(
                    f"Container removal failed during cleanup: {cleanup_err}"
                )

    def cleanup_stopped_containers(
        self, label_filter: Optional[Dict[str, str]] = None
    ):
        """Clean up stopped containers."""
        try:
            filters = {"status": "exited"}
            if label_filter:
                filters["label"] = [
                    f"{k}={v}" for k, v in label_filter.items()
                ]

            containers = self.client.containers.list(filters=filters)
            cleaned_count = 0

            for container in containers:
                try:
                    container.remove()
                    cleaned_count += 1
                    self.logger.info(
                        f"Removed stopped container: {container.short_id}"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Failed to remove container {container.short_id}: {e}"
                    )

            if cleaned_count > 0:
                self.logger.info(
                    f"Cleaned up {cleaned_count} stopped containers"
                )

        except Exception as e:
            self.logger.error(f"Failed to cleanup containers: {e}")

    def list_containers(
        self, all_containers: bool = False
    ) -> List[docker.models.containers.Container]:
        """List containers."""
        try:
            return self.client.containers.list(all=all_containers)
        except Exception as e:
            self.logger.error(f"Failed to list containers: {e}")
            return []

    def get_container_stats(
        self, container: docker.models.containers.Container
    ) -> Dict[str, Any]:
        """Get container resource usage statistics."""
        try:
            stats = container.stats(stream=False)
            return stats
        except Exception as e:
            self.logger.error(f"Failed to get container stats: {e}")
            return {}

    def pull_image(self, image_name: str) -> bool:
        """Pull a Docker image if it doesn't exist locally."""
        try:
            if self.ensure_image_exists(image_name):
                return True

            self.logger.info(f"Pulling Docker image: {image_name}")
            self.client.images.pull(image_name)
            self.logger.info(f"Successfully pulled image: {image_name}")
            return True

        except docker.errors.ImageNotFound:
            self.logger.error(f"Image not found in registry: {image_name}")
            return False
        except docker.errors.APIError as e:
            self.logger.error(f"Failed to pull image {image_name}: {e}")
            return False

    def build_image(
        self, path: str, tag: str, dockerfile: Optional[str] = None
    ) -> bool:
        """Build a Docker image from a Dockerfile."""
        try:
            self.logger.info(f"Building Docker image {tag} from {path}")

            image, build_logs = self.client.images.build(
                path=path,
                tag=tag,
                dockerfile=dockerfile,
                rm=True,
                forcerm=True,
            )

            # Log build output
            for log in build_logs:
                if "stream" in log:
                    self.logger.debug(log["stream"].strip())
                elif "error" in log:
                    self.logger.error(log["error"])
                    return False

            self.logger.info(f"Successfully built image: {tag}")
            return True

        except docker.errors.BuildError as e:
            self.logger.error(f"Failed to build image {tag}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error building image {tag}: {e}")
            return False

    def get_image_info(self, image_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a Docker image."""
        try:
            image = self.client.images.get(image_name)
            return {
                "id": image.id,
                "tags": image.tags,
                "created": image.attrs.get("Created"),
                "size": image.attrs.get("Size"),
                "config": image.attrs.get("Config", {}),
            }
        except docker.errors.ImageNotFound:
            return None
        except Exception as e:
            self.logger.error(
                f"Failed to get image info for {image_name}: {e}"
            )
            return None
