"""Extra Sphinx configuration for Jupyter Book.

This file is automatically sourced by Jupyter Book's Sphinx build.
It sets up sys.path and mocks modules needed for autodoc.
"""
import os
import sys
from unittest.mock import MagicMock

# Set environment variables before any imports
os.environ.setdefault('DATA_PATH', 'c:\\temp\\haste_data')
os.environ.setdefault('AZURE_STORAGE_CONNECTION_STRING', 'mock_connection_string')
os.environ.setdefault('COSMOS_CONNECTION_STRING', 'mock_cosmos_string')

# Add project paths so autodoc can find modules
sys.path.insert(0, os.path.abspath('..'))
sys.path.insert(0, os.path.abspath('../api'))
sys.path.insert(0, os.path.abspath('../api/hastefuncapi'))
sys.path.insert(0, os.path.abspath('../api/hastefuncqueues'))
sys.path.insert(0, os.path.abspath('../hastelib/src'))
sys.path.insert(0, os.path.abspath('.'))


# Mock modules that aren't available during doc build
class _Mock(MagicMock):
    @classmethod
    def __getattr__(cls, name):
        return MagicMock()


_MOCK_MODULES = [
    # System-library deps that can't pip install on all platforms
    'osgeo', 'osgeo.gdal', 'osgeo.ogr', 'osgeo.osr',
    'rasterio', 'rasterio.io', 'rasterio.warp',
    'cv2',
]
sys.modules.update((mod, _Mock()) for mod in _MOCK_MODULES)
