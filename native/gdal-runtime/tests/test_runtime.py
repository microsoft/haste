import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assemble_wheels  # noqa: E402
import baseline_report  # noqa: E402
import fetch_sources  # noqa: E402
import haste_gdal_runtime as rt  # noqa: E402
from haste_gdal_runtime._native import mapped_libraries  # noqa: E402
from verify_build_manifest import validate as validate_manifest  # noqa: E402

LIB = Path("/opt/libs/libgdal-abc.so.38")
PROJ_LIB = "/opt/libs/libproj-abc.so.25"

MANIFEST = {
    "gdal_release": "3.13.3",
    "proj_release": "9.8.1",
    "drivers": ["GTiff", "COG", "VRT", "MEM", "PNG", "GPKG"],
    "vsi_prefixes": ["/vsimem/", "/vsicurl/", "/vsisubfile/"],
    "vrt_raw_band_compiled": False,
    "probes_permissive": {
        "raw_band": "rejected",
        "python_pixel_function": "rejected",
    },
}


def good_report():
    ca = os.path.abspath(__file__)
    return {
        "library": str(LIB),
        "gdal_release": "3.13.3",
        "drivers": ["GTiff", "VRT", "MEM"],
        "vsi_prefixes": ["/vsimem/", "/vsicurl/"],
        "vrt_raw_band_compiled": False,
        "config": {
            **rt.REQUIRED_CONFIG,
            **{k: str(v) for k, v in rt.PINNED_PATHS.items()},
            "CURL_CA_BUNDLE": ca,
        },
        "ca_bundle": {"path": ca, "exists": True},
        "mapped_libgdal": [str(LIB)],
        "mapped_libproj": [PROJ_LIB],
        "bindings": {
            "osgeo.gdal": {"version": "3.13.3", "gdal": "3.13.3"},
            "pyproj": {"version": "3.7.2", "proj": "9.8.1"},
        },
        "probes": {
            "raw_band": "rejected",
            "python_pixel_function": "read-failed",
            "vrt_driver": "opened",
        },
        "probes_permissive": {
            "raw_band": "rejected",
            "python_pixel_function": "rejected",
        },
    }


class LockTests(unittest.TestCase):
    def test_shipped_lock_parses(self):
        text = (ROOT / "sources.lock").read_text(encoding="utf-8")
        build, sources = fetch_sources.parse_lock(text)
        self.assertTrue(build.isdigit())
        self.assertIn("gdal", {s.name for s in sources})

    def test_rejects_plain_http(self):
        line = "HASTE_GDAL_BUILD 1\nx 1 http://a/x.tgz " + "a" * 64
        with self.assertRaises(ValueError):
            fetch_sources.parse_lock(line)

    def test_rejects_bad_digest(self):
        line = "HASTE_GDAL_BUILD 1\nx 1 https://a/x.tgz " + "A" * 64
        with self.assertRaises(ValueError):
            fetch_sources.parse_lock(line)

    def test_rejects_duplicates_and_missing_build(self):
        row = "x 1 https://a/x.tgz " + "a" * 64
        with self.assertRaises(ValueError):
            fetch_sources.parse_lock("HASTE_GDAL_BUILD 1\n" + row + "\n" + row)
        with self.assertRaises(ValueError):
            fetch_sources.parse_lock(row)

    def test_python_sdists_are_not_in_native_fetch_lock(self):
        text = (ROOT / "sources.lock").read_text(encoding="utf-8")
        self.assertNotIn("pythonhosted.org", text)

    def test_binding_build_helpers_require_explicit_feed(self):
        for name in ("install_build_tools.sh", "fetch_binding_sdists.sh"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("PIP_INDEX_URL", text)
            self.assertIn("--index-url", text)
            self.assertNotIn("pypi.org/simple", text)
        build_bindings = (ROOT / "build_bindings.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--no-index"', build_bindings)

    def test_build_workflow_uses_only_the_protected_internal_feed(self):
        workflow = (
            ROOT.parents[1]
            / ".github"
            / "workflows"
            / "gdal-runtime-build.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("secrets.PIP_INDEX_URL", workflow)
        self.assertIn("environment: gdal-runtime-build", workflow)
        self.assertIn("--no-index", (ROOT / "smoke_test.py").read_text())
        self.assertNotIn("packagefeedproxy.microsoft.io", workflow)


class WheelAssemblyTests(unittest.TestCase):
    def test_maps_binding_data_into_the_combined_wheel(self):
        member = "rasterio-1.4.4.data/platlib/rasterio/_base.so"
        staging = assemble_wheels.rewrite_data_path(
            member, "haste_gdal_runtime-3.13.3+haste.1.data"
        )
        self.assertEqual(
            staging,
            "haste_gdal_runtime-3.13.3+haste.1.data/platlib/"
            "rasterio/_base.so",
        )
        output = assemble_wheels.restore_data_path(
            staging, "rasterio", "1.4.4+haste.1"
        )
        self.assertEqual(
            output,
            "rasterio-1.4.4+haste.1.data/platlib/rasterio/_base.so",
        )

    def test_binding_metadata_pins_runtime_and_removes_old_runtime(self):
        metadata = (
            b"Metadata-Version: 2.1\n"
            b"Name: rasterio\n"
            b"Version: 1.4.4\n"
            b"Requires-Dist: haste-gdal-runtime>=3\n"
            b"Requires-Dist: numpy\n"
        )
        updated = assemble_wheels.update_metadata(
            metadata, "1.4.4+haste.1", "3.13.3+haste.1"
        )
        self.assertIn(b"Version: 1.4.4+haste.1", updated)
        self.assertIn(
            b"Requires-Dist: haste-gdal-runtime==3.13.3+haste.1", updated
        )
        self.assertIn(b"Requires-Dist: numpy", updated)
        self.assertNotIn(b"haste-gdal-runtime>=3", updated)

    def test_local_version_discards_any_existing_local_suffix(self):
        self.assertEqual(
            assemble_wheels.local_version("1.2.3+source", "7"),
            "1.2.3+haste.7",
        )


class MappedLibrariesTests(unittest.TestCase):
    MAPS = (
        "7f00-7f01 r-xp 0 00:00 1 /a/libgdal-1.so.38\n"
        "7f02-7f03 r--p 0 00:00 1 /a/libgdal-1.so.38\n"
        "7f04-7f05 r-xp 0 00:00 2 /b/libgdal.so.36\n"
        "7f06-7f07 r-xp 0 00:00 3 /c/libgdal_extra.txt\n"
        "7f08-7f09 r-xp 0 00:00 0\n"
    )

    def test_distinct_paths(self):
        self.assertEqual(
            mapped_libraries("libgdal", self.MAPS),
            ["/a/libgdal-1.so.38", "/b/libgdal.so.36"],
        )

    def test_none_found(self):
        self.assertEqual(mapped_libraries("libproj", self.MAPS), [])

    def test_baseline_report_records_distinct_native_libraries(self):
        report = baseline_report.collect_report(self.MAPS)
        self.assertEqual(
            report["libraries"]["libgdal"],
            ["/a/libgdal-1.so.38", "/b/libgdal.so.36"],
        )
        self.assertEqual(report["libraries"]["libproj"], [])
        self.assertIsNone(report["native"]["library"])


class ConfigureTests(unittest.TestCase):
    def test_sets_defaults_and_keeps_operator_values(self):
        env = {"GDAL_DISABLE_READDIR_ON_OPEN": "TRUE"}
        rt.configure(environ=env)
        self.assertEqual(env["GDAL_VRT_ENABLE_RAWRASTERBAND"], "NO")
        self.assertEqual(env["GDAL_DRIVER_PATH"], "disable")
        self.assertEqual(env["GDAL_DISABLE_READDIR_ON_OPEN"], "TRUE")
        self.assertEqual(env["GDAL_DATA"], str(rt.GDAL_DATA_DIR))

    def test_skip_list_merges_with_existing(self):
        policy = rt.Policy("3.13.3", allowed_drivers=frozenset({"GTiff"}))
        env = {"GDAL_SKIP": "PNG, Foo"}
        rt.configure(policy, environ=env, manifest=MANIFEST)
        self.assertEqual(
            sorted(env["GDAL_SKIP"].split(",")),
            ["COG", "Foo", "GPKG", "MEM", "PNG", "VRT"],
        )

    def test_skip_list_empty_without_allowlist(self):
        self.assertEqual(rt.skip_list(MANIFEST, rt.Policy("3.13.3")), [])


class EvaluateTests(unittest.TestCase):
    policy = rt.Policy("3.13.3")

    def run_eval(self, observed, manifest=MANIFEST, policy=None):
        return rt.evaluate(observed, manifest, policy or self.policy)

    def test_good_report_has_no_problems(self):
        self.assertEqual(self.run_eval(good_report()), [])

    def test_wrong_version(self):
        observed = good_report()
        observed["gdal_release"] = "3.12.0"
        self.assertTrue(self.run_eval(observed))

    def test_binding_on_other_gdal(self):
        observed = good_report()
        observed["bindings"]["osgeo.gdal"]["gdal"] = "3.9.2"
        self.assertTrue(self.run_eval(observed))

    def test_second_libgdal(self):
        observed = good_report()
        observed["mapped_libgdal"].append("/x/libgdal.so.36")
        self.assertTrue(self.run_eval(observed))

    def test_unknown_driver_and_vsi(self):
        observed = good_report()
        observed["drivers"].append("HDF5")
        observed["vsi_prefixes"].append("/vsis3/")
        self.assertEqual(len(self.run_eval(observed)), 3)

    def test_relaxed_config(self):
        observed = good_report()
        observed["config"]["GDAL_VRT_ENABLE_RAWRASTERBAND"] = "YES"
        observed["config"]["GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE"] = "ALL"
        self.assertEqual(len(self.run_eval(observed)), 2)

    def test_raw_band_compiled_in(self):
        observed = good_report()
        observed["vrt_raw_band_compiled"] = True
        self.assertTrue(self.run_eval(observed))

    def test_probe_that_succeeds(self):
        observed = good_report()
        observed["probes_permissive"]["python_pixel_function"] = "opened"
        self.assertTrue(self.run_eval(observed))

    def test_vrt_must_be_rejected_when_not_allowed(self):
        policy = rt.Policy("3.13.3", allowed_drivers=frozenset({"GTiff"}))
        observed = good_report()
        observed["drivers"] = ["GTiff"]
        problems = self.run_eval(observed, policy=policy)
        self.assertEqual(len(problems), 1)
        self.assertIn("VRT", problems[0])

    def test_missing_ca_bundle(self):
        observed = good_report()
        observed["ca_bundle"] = {"path": None, "exists": False}
        self.assertTrue(self.run_eval(observed))

    def test_missing_required_binding(self):
        policy = rt.Policy("3.13.3", required_bindings=("rasterio",))
        self.assertTrue(self.run_eval(good_report(), policy=policy))


class ManifestTests(unittest.TestCase):
    def test_approved_manifest_is_accepted(self):
        manifest = {
            "gdal_release": "3.13.3",
            "proj_release": "9.8.1",
            "vrt_raw_band_compiled": False,
            "drivers": sorted(
                {
                    "COG",
                    "GTiff",
                    "VRT",
                    "MEM",
                    "PNG",
                    "JPEG",
                    "GeoJSON",
                    "GeoJSONSeq",
                    "ESRIJSON",
                    "TopoJSON",
                    "GPKG",
                    "SQLite",
                }
            ),
            "probes_permissive": {
                "raw_band": "rejected",
                "python_pixel_function": "read-failed",
            },
        }
        self.assertEqual(validate_manifest(manifest), [])

    def test_manifest_rejects_extra_driver_or_enabled_raw_band(self):
        manifest = {
            "gdal_release": "3.13.3",
            "proj_release": "9.8.1",
            "vrt_raw_band_compiled": True,
            "drivers": ["GTiff", "HDF5"],
            "probes_permissive": {
                "raw_band": "read",
                "python_pixel_function": "rejected",
            },
        }
        errors = validate_manifest(manifest)
        self.assertGreaterEqual(len(errors), 3)
        self.assertTrue(any("inventory" in error for error in errors))

    def test_manifest_rejects_unapproved_proj_release(self):
        manifest = {
            "gdal_release": "3.13.3",
            "proj_release": "9.7.0",
            "vrt_raw_band_compiled": False,
            "drivers": sorted(
                {
                    "COG",
                    "GTiff",
                    "VRT",
                    "MEM",
                    "PNG",
                    "JPEG",
                    "GeoJSON",
                    "GeoJSONSeq",
                    "ESRIJSON",
                    "TopoJSON",
                    "GPKG",
                    "SQLite",
                }
            ),
            "probes_permissive": {
                "raw_band": "rejected",
                "python_pixel_function": "read-failed",
            },
        }
        self.assertTrue(
            any(
                "PROJ release" in error
                for error in validate_manifest(manifest)
            )
        )


if __name__ == "__main__":
    unittest.main()
