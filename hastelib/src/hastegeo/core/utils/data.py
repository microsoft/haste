# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import glob
import os
import re

from .logs import Logger

logger = Logger.get_logger(__name__)


def extract_from_url(url, pattern):
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    else:
        return None


def convert_json_to_geojson(input_json):
    # Transform the JSON data into GeoJSON format
    geojson_data = {
        "type": "FeatureCollection",
        "name": input_json.get("name"),
        "features": [],
    }

    for item in input_json.get("labels", []):
        feature = {
            "type": "Feature",
            "geometry": item["geometry"],
            "properties": item["properties"],
        }
        geojson_data["features"].append(feature)
    return geojson_data


def get_distinct_label_classes(label_data, key="primaryClass"):
    classes = set()
    for item in label_data.get("labels", []):
        classes.add(item.get("properties", {}).get(key))
    return list(classes)


def directory_cleanup(directory: str):
    # Delete all local files and manage errors
    for file_path in glob.glob(os.path.join(directory, "*")):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Error deleting {file_path}: {str(e)}")
            return False

    # Once the directory is empty, delete the directory itself
    try:
        os.rmdir(directory)
    except Exception as e:
        logger.error(f"Error deleting directory {directory}: {str(e)}")
        return False

    return True


def filter_roles(roles):
    return [r for r in roles if r not in ("anonymous", "authenticated")]
