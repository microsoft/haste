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

from .gdal_security import max_download_bytes
from .logs import Logger
from .url_allowlist import validate_imagery_url


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
        # "maxar" is the pre-rebrand source-type key; image layers created
        # before the Vantor rename still carry it, so accept both.
        if self.sourceType in ("vantor", "maxar"):
            return self.download_vantor_imagery_post_pre(**kwargs)
        elif self.sourceType == "planet":
            return self.download_planet_imagery_post_pre(**kwargs)
        else:
            urls = kwargs.get("urls", [])
            dst_directory = kwargs.get("dst_directory", "./downloads")
            azure_urls = []
            aws_urls = []
            # Allowlisted hosts without a dedicated SDK path (e.g. Source
            # Cooperative / data.source.coop, used by the Planet Open Data
            # catalog) are fetched over plain HTTPS via
            # download_imagery_from_urls.
            http_urls = []

            for url in urls:
                try:
                    url_type = self._validate_url(url)
                    if url_type == "azureblobstorage":
                        azure_urls.append(url)
                    elif url_type == "awss3":
                        aws_urls.append(url)
                    else:
                        http_urls.append(url)
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
            if http_urls:
                file_paths.extend(
                    self.download_imagery_from_urls(http_urls, dst_directory)
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
            max_bytes = max_download_bytes()

            for url in urls:
                # Defense-in-depth: never fetch a URL whose host is not on the
                # allowlist, even if a caller bypassed download_imagery().
                try:
                    self._validate_url(url)
                except ValueError as e:
                    self.logger.warning(f"Skipping URL not in allowlist: {e}")
                    continue
                # allow_redirects=False so an allowlisted source can't bounce
                # the fetch to an internal host (SSRF guard); stream so the
                # body can be size-capped before it is buffered to disk.
                response = requests.get(
                    url, allow_redirects=False, stream=True, timeout=60
                )
                if response.status_code in (301, 302, 303, 307, 308):
                    self.logger.warning(
                        "Refusing redirect for imagery URL %s (status %s)",
                        url,
                        response.status_code,
                    )
                    response.close()
                    continue
                if response.status_code != 200:
                    self.logger.error(f"Failed to fetch data from URL: {url}")
                    response.close()
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
                if self._stream_to_file(response, image_path, max_bytes, url):
                    file_paths.append(image_path)

            self.logger.info("Download complete.")
            return file_paths
        except Exception as e:
            self.logger.error(f"Error occurred while downloading imagery: {e}")
            raise e

    def _stream_to_file(self, response, image_path, max_bytes, url):
        """Stream a response body to ``image_path``, capped at ``max_bytes``.

        Returns ``True`` on success. If the body exceeds ``max_bytes``
        (via ``Content-Length`` or while streaming), the partial file is
        removed and ``False`` is returned so the URL is skipped without
        failing the whole batch. Bounds memory + disk against a hostile or
        accidental multi-GB response.
        """
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    self.logger.warning(
                        "Imagery %s exceeds max size %d "
                        "(Content-Length %s); skipping.",
                        url,
                        max_bytes,
                        content_length,
                    )
                    response.close()
                    return False
            except (TypeError, ValueError):
                pass

        written = 0
        oversize = False
        try:
            with open(image_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        oversize = True
                        break
                    file.write(chunk)
        finally:
            response.close()

        if oversize:
            self.logger.warning(
                "Imagery %s exceeded max size %d mid-stream; aborting.",
                url,
                max_bytes,
            )
            if os.path.exists(image_path):
                os.remove(image_path)
            return False
        return True

    def _validate_url(self, url: str) -> str:
        return validate_imagery_url(url)

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

            # Size guard at the download boundary: skip blobs larger than
            # the cap (cheap properties call, no body transfer).
            try:
                blob_size = blob_client.get_blob_properties().size
                if blob_size and blob_size > max_download_bytes():
                    self.logger.warning(
                        "Blob %s exceeds max size %d (%d bytes); skipping.",
                        url,
                        max_download_bytes(),
                        blob_size,
                    )
                    continue
            except Exception as err:
                self.logger.warning(
                    "Could not read blob properties for %s: %s", url, err
                )

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
                    head = s3.head_object(Bucket=bucket, Key=key)
                    obj_size = head.get("ContentLength")
                    if obj_size and obj_size > max_download_bytes():
                        self.logger.warning(
                            "S3 object %s exceeds max size %d (%s bytes); "
                            "skipping.",
                            url,
                            max_download_bytes(),
                            obj_size,
                        )
                        continue
                except Exception as err:
                    self.logger.warning(
                        "Could not head S3 object %s: %s", url, err
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

    def download_vantor_imagery_post_pre(self, event_name, save_directory):
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
