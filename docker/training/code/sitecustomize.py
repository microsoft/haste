"""Harden GDAL before any training-process module can import a binding."""

from hastegeo.core.utils.gdal_security import harden_gdal

harden_gdal()
