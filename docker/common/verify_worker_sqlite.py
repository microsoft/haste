#!/usr/bin/env python3
"""Verify Python SQLite and GDAL GeoPackage operations in worker images."""

import sqlite3
import tempfile
from pathlib import Path


def verify_worker_sqlite() -> None:
    from hastegeo.core.utils.gdal_security import harden_gdal

    harden_gdal()
    from osgeo import ogr

    ogr.UseExceptions()
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE example (value INTEGER)")
        connection.execute("INSERT INTO example VALUES (7)")
        if connection.execute("SELECT value FROM example").fetchone() != (7,):
            raise RuntimeError("Python SQLite returned an unexpected result")

    driver = ogr.GetDriverByName("GPKG")
    if driver is None:
        raise RuntimeError("GDAL GeoPackage driver is unavailable")
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "smoke.gpkg")
        dataset = driver.CreateDataSource(path)
        if dataset is None:
            raise RuntimeError("Unable to create a GeoPackage")
        layer = dataset.CreateLayer("test", geom_type=ogr.wkbNone)
        if (
            layer is None
            or layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger)) != 0
        ):
            raise RuntimeError("Unable to create GeoPackage layer")
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("value", 7)
        if layer.CreateFeature(feature) != 0:
            raise RuntimeError("Unable to write GeoPackage feature")
        feature = layer = dataset = None
        dataset = ogr.Open(path)
        if dataset is None:
            raise RuntimeError("Unable to reopen a GeoPackage")
        layer = dataset.GetLayerByName("test")
        feature = layer.GetNextFeature() if layer else None
        if feature is None or feature.GetField("value") != 7:
            raise RuntimeError("GeoPackage read did not return expected data")
        feature = layer = dataset = None


if __name__ == "__main__":
    verify_worker_sqlite()
