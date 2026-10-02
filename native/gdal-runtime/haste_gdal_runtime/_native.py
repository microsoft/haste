"""ctypes access to the runtime's libgdal.

The self-check talks to libgdal directly instead of going through a binding.
The same check then works in runtimes that only install rasterio, such as the
tile server, and it inspects the one library every binding links to.
"""

from __future__ import annotations

import ctypes
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

GDAL_OF_RASTER = 0x02
GF_READ = 0
GDT_BYTE = 1

# Settings that would allow each probed feature if it were compiled in.
# Probing under them proves the feature is absent from the binary, not just
# switched off by configuration.
PERMISSIVE_CONFIG = {
    "GDAL_VRT_ENABLE_RAWRASTERBAND": "YES",
    "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE": "ALL",
    "GDAL_VRT_ENABLE_PYTHON": "YES",
}

_RAW_BAND_VRT = """<VRTDataset rasterXSize="1" rasterYSize="1">
  <VRTRasterBand dataType="Byte" band="1" subClass="VRTRawRasterBand">
    <SourceFilename relativeToVRT="1">raw.bin</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>1</PixelOffset>
    <LineOffset>1</LineOffset>
  </VRTRasterBand>
</VRTDataset>"""

# Harmless if it ever ran: it only fills the output buffer. Any successful
# read through it fails the check.
_PYTHON_PIXEL_FUNCTION_VRT = """<VRTDataset rasterXSize="1" rasterYSize="1">
  <VRTRasterBand dataType="Byte" band="1" subClass="VRTDerivedRasterBand">
    <PixelFunctionType>haste_probe</PixelFunctionType>
    <PixelFunctionLanguage>Python</PixelFunctionLanguage>
    <PixelFunctionCode><![CDATA[
def haste_probe(in_ar, out_ar, *args, **kwargs):
    out_ar[:] = 1
]]></PixelFunctionCode>
  </VRTRasterBand>
</VRTDataset>"""

_PLAIN_VRT = """<VRTDataset rasterXSize="1" rasterYSize="1">
  <VRTRasterBand dataType="Byte" band="1"/>
</VRTDataset>"""


class NativeGdal:
    """The subset of the GDAL C API the runtime check needs."""

    def __init__(self, library: Path) -> None:
        self.path = Path(library)
        self._lib = ctypes.CDLL(str(self.path))
        self._declare()
        # Register only when nothing has yet. GDALAllRegister would bring
        # back drivers that a hardened process has deregistered.
        if self._lib.GDALGetDriverCount() == 0:
            self._lib.GDALAllRegister()

    def _declare(self) -> None:
        lib = self._lib
        c_char_p, c_int, c_void_p = (
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_void_p,
        )
        signatures = {
            "GDALAllRegister": ([], None),
            "GDALVersionInfo": ([c_char_p], c_char_p),
            "GDALGetDriverCount": ([], c_int),
            "GDALGetDriver": ([c_int], c_void_p),
            "GDALGetDriverByName": ([c_char_p], c_void_p),
            "GDALGetDriverShortName": ([c_void_p], c_char_p),
            "GDALDeregisterDriver": ([c_void_p], None),
            "GDALGetMetadataItem": ([c_void_p, c_char_p, c_char_p], c_char_p),
            "VSIGetFileSystemsPrefixes": ([], ctypes.POINTER(c_char_p)),
            "VSIRemovePluginHandler": ([c_char_p], c_int),
            "CSLDestroy": ([ctypes.POINTER(c_char_p)], None),
            "CPLGetConfigOption": ([c_char_p, c_char_p], c_char_p),
            "CPLGetThreadLocalConfigOption": ([c_char_p, c_char_p], c_char_p),
            "CPLSetThreadLocalConfigOption": ([c_char_p, c_char_p], None),
            "CPLPushErrorHandler": ([c_void_p], None),
            "CPLPopErrorHandler": ([], None),
            "CPLErrorReset": ([], None),
            "GDALOpenEx": (
                [c_char_p, ctypes.c_uint, c_void_p, c_void_p, c_void_p],
                c_void_p,
            ),
            "GDALGetRasterBand": ([c_void_p, c_int], c_void_p),
            "GDALRasterIO": (
                [c_void_p] + [c_int] * 5 + [c_void_p] + [c_int] * 5,
                c_int,
            ),
            "GDALClose": ([c_void_p], c_int),
        }
        for name, (argtypes, restype) in signatures.items():
            function = getattr(lib, name)
            function.argtypes = argtypes
            function.restype = restype

    @staticmethod
    def _text(value: bytes | None) -> str | None:
        return None if value is None else value.decode("utf-8", "replace")

    def version_info(self, request: str) -> str:
        return self._text(self._lib.GDALVersionInfo(request.encode())) or ""

    def build_info(self) -> dict[str, str]:
        info = {}
        for line in self.version_info("BUILD_INFO").splitlines():
            key, _, value = line.partition("=")
            if key:
                info[key.strip()] = value.strip()
        return info

    def _driver_handles(self) -> dict[str, int]:
        handles = {}
        for index in range(self._lib.GDALGetDriverCount()):
            driver = self._lib.GDALGetDriver(index)
            if driver:
                name = self._text(self._lib.GDALGetDriverShortName(driver))
                handles[name or ""] = driver
        return handles

    def drivers(self) -> list[str]:
        return sorted(self._driver_handles())

    def driver_metadata(self, driver: str, key: str) -> str | None:
        handle = self._lib.GDALGetDriverByName(driver.encode())
        if not handle:
            return None
        return self._text(
            self._lib.GDALGetMetadataItem(handle, key.encode(), None)
        )

    def deregister_drivers(self, names: set[str]) -> list[str]:
        removed = []
        for name, handle in self._driver_handles().items():
            if name in names:
                self._lib.GDALDeregisterDriver(handle)
                removed.append(name)
        return sorted(removed)

    def vsi_prefixes(self) -> list[str]:
        prefixes = self._lib.VSIGetFileSystemsPrefixes()
        names = []
        index = 0
        while prefixes and prefixes[index]:
            names.append(prefixes[index].decode("utf-8", "replace"))
            index += 1
        self._lib.CSLDestroy(prefixes)
        return sorted(names)

    def remove_vsi_handlers(self, prefixes: set[str]) -> list[str]:
        removed = []
        for prefix in sorted(prefixes & set(self.vsi_prefixes())):
            self._lib.VSIRemovePluginHandler(prefix.encode())
            removed.append(prefix)
        return removed

    def config(self, key: str) -> str | None:
        return self._text(self._lib.CPLGetConfigOption(key.encode(), None))

    @contextmanager
    def _thread_config(self, values: dict[str, str]) -> Iterator[None]:
        previous = {
            key: self._lib.CPLGetThreadLocalConfigOption(key.encode(), None)
            for key in values
        }
        for key, value in values.items():
            self._lib.CPLSetThreadLocalConfigOption(
                key.encode(), value.encode()
            )
        try:
            yield
        finally:
            for key, value in previous.items():
                self._lib.CPLSetThreadLocalConfigOption(key.encode(), value)

    @contextmanager
    def _quiet(self) -> Iterator[None]:
        handler = ctypes.cast(self._lib.CPLQuietErrorHandler, ctypes.c_void_p)
        self._lib.CPLPushErrorHandler(handler)
        try:
            yield
        finally:
            self._lib.CPLPopErrorHandler()
            self._lib.CPLErrorReset()

    def try_read(self, filename: str) -> str:
        """Open ``filename`` as a raster and read one pixel.

        Returns "rejected" when GDAL refuses to open it, "read-failed" when
        it opens but refuses the read, and "read" when the read succeeds.
        """
        with self._quiet():
            dataset = self._lib.GDALOpenEx(
                filename.encode(), GDAL_OF_RASTER, None, None, None
            )
            if not dataset:
                return "rejected"
            try:
                band = self._lib.GDALGetRasterBand(dataset, 1)
                if not band:
                    return "read-failed"
                buffer = (ctypes.c_ubyte * 1)()
                error = self._lib.GDALRasterIO(
                    band, GF_READ, 0, 0, 1, 1, buffer, 1, 1, GDT_BYTE, 0, 0
                )
                return "read" if error == 0 else "read-failed"
            finally:
                self._lib.GDALClose(dataset)

    def probes(self, *, permissive: bool = False) -> dict[str, str]:
        """Try the VRT features the runtime must never allow.

        With ``permissive`` the probes run under settings that would allow
        each feature, so a refusal shows the feature is not in the build.
        """
        settings = PERMISSIVE_CONFIG if permissive else {}
        with tempfile.TemporaryDirectory(prefix="haste-gdal-probe-") as tmp:
            (Path(tmp) / "raw.bin").write_bytes(b"\x01")
            raw_vrt = Path(tmp) / "raw.vrt"
            raw_vrt.write_text(_RAW_BAND_VRT, encoding="utf-8")
            with self._thread_config(settings):
                return {
                    "raw_band": self.try_read(str(raw_vrt)),
                    "python_pixel_function": self.try_read(
                        _PYTHON_PIXEL_FUNCTION_VRT
                    ),
                    "vrt_driver": self.try_read(_PLAIN_VRT),
                }


def mapped_libraries(stem: str, maps_text: str | None = None) -> list[str]:
    """Distinct mapped shared objects whose file name starts with ``stem``.

    Linux only. Every binding links to the runtime's copy, so more than one
    path means some package brought its own library.
    """
    if maps_text is None:
        try:
            maps_text = Path("/proc/self/maps").read_text(encoding="utf-8")
        except OSError:
            return []
    paths = set()
    for line in maps_text.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        path = fields[5].strip()
        name = os.path.basename(path)
        if name.startswith(stem) and ".so" in name:
            paths.add(path)
    return sorted(paths)
