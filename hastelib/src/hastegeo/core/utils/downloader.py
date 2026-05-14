# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
from logging import INFO
from urllib.parse import urlparse

import boto3  # type: ignore
import requests  # type: ignore
from azure.storage.blob import BlobClient  # type: ignore
from botocore import UNSIGNED  # type: ignore # type: ignore
from botocore.client import Config  # type: ignore # type: ignore
from botocore.exceptions import ClientError  # type: ignore
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .logs import Logger


class ImageryDownloader:
    def __init__(
        self,
        sourceType: str,
        log_dir: str = None,
        log_file: int = None,
        log_level: int = INFO,
    ):
        self.sourceType = sourceType.lower()
        self.logger = Logger.get_logger(
            __name__, log_dir=log_dir, log_file=log_file, level=log_level
        )

    def download_imagery(self, **kwargs):
        if self.sourceType == "maxar":
            return self.download_maxar_imagery_post_pre(**kwargs)
        elif self.sourceType == "planet":
            return self.download_planet_imagery_post_pre(**kwargs)
        else:
            urls = kwargs.get("urls", [])
            dst_directory = kwargs.get("dst_directory", "./downloads")
            azure_urls = []
            aws_urls = []

            for url in urls:
                try:
                    url_type = self._validate_url(url)
                    if url_type == "azureblobstorage":
                        azure_urls.append(url)
                    elif url_type == "awss3":
                        aws_urls.append(url)
                except Exception as e:
                    self.logger.warning(f"Skipping URL not in allowlist: {e}")

            file_paths = []
            if azure_urls:
                file_paths.extend(
                    self.download_azure_blob_files(azure_urls, dst_directory)
                )
            if aws_urls:
                file_paths.extend(
                    self.download_aws_s3_files(aws_urls, dst_directory)
                )
            return file_paths

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
        ),
    )
    def download_imagery_from_urls(self, urls: list, dst_directory: str):
        try:
            if dst_directory:
                os.makedirs(dst_directory, exist_ok=True)
            urls = list(set(urls))
            file_paths = []
            existing_names = set()

            for url in urls:
                # Defense-in-depth: never fetch a URL whose host is not on the
                # allowlist, even if a caller bypassed download_imagery().
                try:
                    self._validate_url(url)
                except ValueError as e:
                    self.logger.warning(f"Skipping URL not in allowlist: {e}")
                    continue
                response = requests.get(url)
                if response.status_code != 200:
                    self.logger.error(f"Failed to fetch data from URL: {url}")
                    continue

                image_name = os.path.basename(url)
                image_path = os.path.join(dst_directory, image_name)

                # Ensure unique image names
                base_name, extension = os.path.splitext(image_name)
                counter = 1
                while image_name in existing_names:
                    image_name = f"{base_name}_{counter}.{extension}"
                    image_path = os.path.join(dst_directory, image_name)
                    counter += 1

                existing_names.add(image_name)

                self.logger.info(f"Downloading {image_name}...")
                with open(image_path, "wb") as file:
                    file.write(response.content)
                    file_paths.append(image_path)

            self.logger.info("Download complete.")
            return file_paths
        except Exception as e:
            self.logger.error(f"Error occurred while downloading imagery: {e}")
            raise e

    def _validate_url(self, url: str) -> str:
        """Validate a remote imagery URL against the allowlist of permitted hosts.

        Returns a string identifying the source type. Raises ValueError if the
        URL is malformed or the host is not on the allowlist — callers must
        treat this as a hard rejection (no fallback to arbitrary HTTP fetch).
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")

        host = parsed.hostname
        if not host:
            raise ValueError("URL is missing host component")

        if host == "blob.core.windows.net" or host.endswith(
            ".blob.core.windows.net"
        ):
            return "azureblobstorage"

        if (
            host == "s3.amazonaws.com"
            or host.endswith(".s3.amazonaws.com")
            or host.endswith(".amazonaws.com")
        ):
            return "awss3"

        raise ValueError(
            f"URL host {host!r} is not on the allowlist of permitted imagery sources"
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def download_azure_blob_files(self, urls: list, dst_directory: str):
        if dst_directory and not os.path.exists(dst_directory):
            os.makedirs(dst_directory, exist_ok=True)

        file_paths = []
        existing_names = set()

        for url in set(urls):
            try:
                blob_client = BlobClient.from_blob_url(url)
                blob_name = os.path.basename(blob_client.blob_name)
            except Exception as err:
                self.logger.error(
                    f"Failed to initialize blob client for URL {url}. Error: {err}"
                )
                raise err

            file_name = blob_name
            file_path = os.path.join(dst_directory, file_name)
            base_name, extension = os.path.splitext(file_name)
            counter = 1

            while file_name in existing_names or os.path.exists(file_path):
                file_name = f"{base_name}_{counter}{extension}"
                file_path = os.path.join(dst_directory, file_name)
                counter += 1

            existing_names.add(file_name)
            self.logger.info(f"Downloading {file_name}...")

            try:
                with open(file_path, "wb") as file:
                    download_stream = blob_client.download_blob()
                    file.write(download_stream.readall())
                file_paths.append(file_path)
            except Exception as err:
                self.logger.error(
                    f"Failed to download blob from URL {url}. Error: {err}"
                )
                raise err

        self.logger.info("Azure Blob download complete.")
        return file_paths

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def download_aws_s3_files(self, urls: list, dst_directory: str):
        try:
            if dst_directory and not os.path.exists(dst_directory):
                os.makedirs(dst_directory)

            file_paths = []
            existing_names = set()
            try:
                s3 = boto3.client(
                    "s3", config=Config(signature_version=UNSIGNED)
                )
            except ClientError as e:
                self.logger.error(f"Failed to create S3 client: {e}")
                raise e

            for url in set(urls):
                parsed = urlparse(url)
                bucket = None
                key = None

                if parsed.scheme == "s3":
                    # s3://bucket/key
                    path_parts = parsed.path.lstrip("/").split("/", 1)
                    if len(path_parts) != 2:
                        self.logger.error(f"Invalid S3 URL format: {url}")
                        continue
                    bucket, key = path_parts
                elif (
                    parsed.netloc == "s3.amazonaws.com"
                    or parsed.netloc.endswith(".s3.amazonaws.com")
                ):
                    if parsed.netloc == "s3.amazonaws.com":
                        # https://s3.amazonaws.com/bucket/key
                        path_parts = parsed.path.lstrip("/").split("/", 1)
                        if len(path_parts) != 2:
                            self.logger.error(f"Invalid S3 URL format: {url}")
                            continue
                        bucket, key = path_parts
                    else:
                        # https://bucket.s3.amazonaws.com/key
                        bucket = parsed.netloc.split(".s3.amazonaws.com")[0]
                        key = parsed.path.lstrip("/")
                else:
                    self.logger.error(
                        f"URL is not recognized as a valid AWS S3 URL: {url}"
                    )
                    continue

                file_name = os.path.basename(key)
                file_path = os.path.join(dst_directory, file_name)
                base_name, extension = os.path.splitext(file_name)
                counter = 1

                while file_name in existing_names or os.path.exists(file_path):
                    file_name = f"{base_name}_{counter}{extension}"
                    file_path = os.path.join(dst_directory, file_name)
                    counter += 1

                existing_names.add(file_name)
                self.logger.info(
                    f"Downloading {file_name} from bucket {bucket} with key {key}...to file path {file_path}"
                )

                try:
                    s3.download_file(
                        Bucket=bucket, Key=key, Filename=file_path
                    )
                    file_paths.append(file_path)
                except Exception as err:
                    self.logger.error(
                        f"Failed to download file from URL {url}. Error: {err}"
                    )
                    raise err

            self.logger.info("AWS S3 download complete.")
            return file_paths
        except (ConnectionError, TimeoutError) as err:
            self.logger.error(f"Network error occurred: {err}")
            raise err

    def download_maxar_imagery_post_pre(self, event_name, save_directory):
        pass

    def download_planet_imagery_post_pre(
        self,
        api_key,
        item_type,
        asset_type,
        pre_item_id,
        post_item_id,
        save_directory,
    ):
        pass
