import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assemble_wheels  # noqa: E402
import baseline_report  # noqa: E402
import create_supply_chain  # noqa: E402
import fetch_sources  # noqa: E402
import haste_gdal_runtime as rt  # noqa: E402
import smoke_test  # noqa: E402
from haste_gdal_runtime._native import mapped_libraries  # noqa: E402
from verify_build_manifest import validate as validate_manifest  # noqa: E402

LIB = Path("/opt/libs/libgdal-abc.so.38")
PROJ_LIB = "/opt/libs/libproj-abc.so.25"

MANIFEST = {
    "gdal_release": "3.13.3",
    "proj_release": "9.8.1",
    "drivers": [
        "GTiff",
        "COG",
        "VRT",
        "MEM",
        "PNG",
        "GPKG",
        "GNMDatabase",
        "GNMFile",
    ],
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

    def test_binding_build_helpers_default_to_hash_pinned_public_index(self):
        for name in ("install_build_tools.sh", "fetch_binding_sdists.sh"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("PIP_INDEX_URL", text)
            self.assertIn("https://pypi.org/simple", text)
            self.assertIn("--index-url", text)
        fetch_script = (ROOT / "fetch_binding_sdists.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--no-build-isolation", fetch_script)
        build_script = (ROOT / "build.sh").read_text(encoding="utf-8")
        public_index = (
            'PIP_INDEX_URL="${PIP_INDEX_URL:-' 'https://pypi.org/simple}"'
        )
        self.assertIn(public_index, build_script)
        self.assertIn("export PIP_INDEX_URL", build_script)
        build_bindings = (ROOT / "build_bindings.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--no-index"', build_bindings)

    def test_build_workflow_uses_optional_feed_with_public_default(self):
        workflow = (
            ROOT.parents[1]
            / ".github"
            / "workflows"
            / "gdal-runtime-build.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("secrets.PIP_INDEX_URL", workflow)
        self.assertIn("https://pypi.org/simple", workflow)
        self.assertIn("environment: gdal-runtime-build", workflow)
        self.assertIn("requirements-smoke.txt", workflow)
        self.assertIn("dnf install -y nasm openssl", workflow)
        self.assertIn("--require-hashes", workflow)
        self.assertIn("--only-binary=:all:", workflow)
        self.assertIn("--index-url https://pypi.org/simple", workflow)
        smoke_test = (ROOT / "smoke_test.py").read_text()
        self.assertIn("binding_workflow_smoke.py", smoke_test)
        binding_smoke = (ROOT / "binding_workflow_smoke.py").read_text()
        for distribution in (
            "haste-gdal-runtime",
            "GDAL",
            "rasterio",
            "fiona",
            "pyogrio",
            "pyproj",
        ):
            self.assertIn(f'"{distribution}"', smoke_test)
        for version in ("1.4.4", "1.10.1", "0.13.0", "3.7.2"):
            self.assertIn(f'"{version}"', smoke_test)
        for binding in ("rasterio", "fiona", "pyogrio", "pyproj"):
            self.assertIn(binding, binding_smoke)
        self.assertIn("https://127.0.0.1", binding_smoke)
        self.assertIn("WarpedVRT", binding_smoke)
        self.assertIn("BuildVRT", binding_smoke)
        self.assertIn("HTTPS /vsicurl/", binding_smoke)
        self.assertIn("bytes(ogr_geometry.ExportToWkb())", binding_smoke)
        self.assertIn(
            'gdal.SetConfigOption("GDAL_CURL_CA_BUNDLE"', binding_smoke
        )
        self.assertIn("gdal.GetLastErrorMsg()", binding_smoke)
        self.assertIn('compress="ZSTD"', binding_smoke)
        self.assertIn("EXPECTED_BINDINGS", binding_smoke)
        self.assertIn("--no-index", smoke_test)
        self.assertIn("distributions.items()", smoke_test)
        self.assertIn('"osgeo.gdal"', smoke_test)
        self.assertIn("cwd=args.wheel_dir.resolve()", smoke_test)

    def test_build_workflow_smokes_functions_and_imageryprep_base_images(self):
        workflow = (
            ROOT.parents[1]
            / ".github"
            / "workflows"
            / "gdal-runtime-build.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("target-image-smoke:", workflow)
        self.assertIn("actions/download-artifact@", workflow)
        self.assertIn("functions-python311", workflow)
        self.assertIn("imageryprep-python311", workflow)
        self.assertIn(
            "mcr.microsoft.com/azure-functions/python:4-python3.11@sha256:",
            workflow,
        )
        self.assertIn(
            "mcr.microsoft.com/azureml/curated/"
            "minimal-py311-inference:59@sha256:",
            workflow,
        )
        self.assertIn("docker run --rm --entrypoint sh", workflow)
        self.assertIn("haste-gdal-smoke-deps-${{ github.sha }}", workflow)
        self.assertIn("--find-links /smoke-wheels", workflow)
        self.assertIn("--no-index", workflow)
        self.assertIn("dist/*", workflow)
        self.assertIn("vulnerability-scan:", workflow)
        self.assertIn("anchore/scan-action@", workflow)
        self.assertIn("fail-build: true", workflow)
        self.assertIn("severity-cutoff: medium", workflow)
        self.assertIn("attest:", workflow)
        self.assertIn("github.repository == 'microsoft/haste'", workflow)
        self.assertIn("actions/attest@", workflow)
        self.assertIn("sbom-path:", workflow)

    def test_build_script_generates_sbom_notices_and_checksums(self):
        build_script = (ROOT / "build.sh").read_text(encoding="utf-8")
        supply_chain_script = (ROOT / "create_supply_chain.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('python3 "$ROOT/create_supply_chain.py"', build_script)
        self.assertIn("bom.cdx.json", supply_chain_script)
        self.assertIn("THIRD_PARTY_NOTICES.txt", supply_chain_script)
        self.assertIn("SHA256SUMS", supply_chain_script)

    def test_supply_chain_bundle_includes_source_wheel_and_notice_evidence(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "sources"
            wheel_dir = root / "wheels"
            output_dir = root / "output"
            source_dir.mkdir()
            wheel_dir.mkdir()

            source_archive = source_dir / "sample-1.0.tar.gz"
            with tarfile.open(source_archive, "w:gz") as archive:
                content = b"sample license text\n"
                member = tarfile.TarInfo("sample-1.0/LICENSE")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            source_hash = create_supply_chain.sha256(source_archive)
            source_lock = root / "sources.lock"
            source_lock.write_text(
                "HASTE_GDAL_BUILD 1\n"
                f"sample 1.0 https://example.test/sample-1.0.tar.gz "
                f"{source_hash}\n",
                encoding="utf-8",
            )

            distributions = (
                ("haste_gdal_runtime", "haste-gdal-runtime"),
                ("GDAL", "GDAL"),
                ("rasterio", "rasterio"),
                ("fiona", "fiona"),
                ("pyogrio", "pyogrio"),
                ("pyproj", "pyproj"),
            )
            for filename, name in distributions:
                wheel_path = wheel_dir / f"{filename}-1.0-py3-none-any.whl"
                with zipfile.ZipFile(wheel_path, "w") as wheel:
                    wheel.writestr(
                        f"{filename}-1.0.dist-info/METADATA",
                        "Metadata-Version: 2.1\n"
                        f"Name: {name}\n"
                        "Version: 1.0\n"
                        "License: MIT\n\n",
                    )
                    if name == "haste-gdal-runtime":
                        wheel.writestr(
                            f"{filename}-1.0.dist-info/licenses/LICENSE",
                            "runtime license text\n",
                        )
            manifest = root / "manifest.json"
            manifest.write_text('{"gdal_release":"3.13.3"}\n')

            outputs = create_supply_chain.generate(
                source_lock,
                source_dir,
                wheel_dir,
                manifest,
                output_dir,
            )

            bom = json.loads(
                (output_dir / "bom.cdx.json").read_text(encoding="utf-8")
            )
            notices = (output_dir / "THIRD_PARTY_NOTICES.txt").read_text(
                encoding="utf-8"
            )
            checksums = (output_dir / "SHA256SUMS").read_text(encoding="utf-8")

        self.assertEqual(len(outputs), 4)
        self.assertEqual(bom["bomFormat"], "CycloneDX")
        self.assertEqual(len(bom["components"]), 7)
        self.assertIn("sample license text", notices)
        self.assertIn("runtime license text", notices)
        self.assertIn("haste_gdal_runtime-1.0-py3-none-any.whl", checksums)
        self.assertIn("manifest.json", checksums)

    def test_supply_chain_bundle_rejects_changed_locked_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "sources"
            wheel_dir = root / "wheels"
            output_dir = root / "output"
            source_dir.mkdir()
            wheel_dir.mkdir()
            (source_dir / "sample-1.0.tar.gz").write_bytes(b"wrong source")
            (wheel_dir / "placeholder.whl").write_bytes(b"")
            source_lock = root / "sources.lock"
            source_lock.write_text(
                "HASTE_GDAL_BUILD 1\n"
                f"sample 1.0 https://example.test/sample-1.0.tar.gz "
                f'{"0" * 64}\n',
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                create_supply_chain.generate(
                    source_lock,
                    source_dir,
                    wheel_dir,
                    manifest,
                    output_dir,
                )

    def test_binding_smoke_runner_prefers_installed_runtime_over_checkout(
        self,
    ):
        command = smoke_test.binding_smoke_command(
            ROOT / "binding_workflow_smoke.py", "python"
        )

        self.assertEqual(command[1], "-c")
        self.assertIn("runpy.run_path", command[2])
        self.assertIn("sys.path.append", command[2])

    def test_smoke_dependencies_are_exact_and_hash_locked(self):
        requirements = (ROOT / "requirements-smoke.txt").read_text(
            encoding="utf-8"
        )
        for name in (
            "affine",
            "attrs",
            "certifi",
            "click",
            "click-plugins",
            "cligj",
            "numpy",
            "packaging",
            "pyparsing",
        ):
            self.assertIn(f"{name}==", requirements)
        self.assertEqual(requirements.count("--hash=sha256:"), 9)

    def test_build_script_generates_gdal_config_without_gdal_apps(self):
        build_script = (ROOT / "build.sh").read_text(encoding="utf-8")
        self.assertIn("-DBUILD_APPS=OFF", build_script)
        self.assertIn("-DBUILD_APPS=ON", build_script)
        self.assertIn("-DBUILD_PYTHON_BINDINGS=OFF", build_script)
        self.assertIn("-DENABLE_GNM=ON", build_script)
        self.assertIn("--libdir=lib", build_script)
        self.assertIn('"$WORK/gdal-build/apps/gdal-config"', build_script)
        self.assertIn(
            'ln -sfn "$PREFIX/bin/gdal-config" /usr/local/bin/gdal-config',
            build_script,
        )
        self.assertIn('"$PREFIX/bin/gdal-config" --version', build_script)
        self.assertIn("GDAL_VRT_DISABLE_PYTHON", build_script)
        header_file_macro = "CPL_VSIL_CURL_HEADER_FILE_KVP_DISABLED"
        self.assertNotIn(header_file_macro, build_script)

    def test_binding_sdists_are_fetched_after_gdal_config_is_available(self):
        build_script = (ROOT / "build.sh").read_text(encoding="utf-8")
        config_created = build_script.index(
            'install -D -m 755 "$WORK/gdal-build/apps/gdal-config"'
        )
        config_exported = build_script.index(
            'export GDAL_CONFIG="$PREFIX/bin/gdal-config"'
        )
        sdists_fetched = build_script.index(
            'bash "$ROOT/fetch_binding_sdists.sh" "$SOURCES/bindings"'
        )
        binding_build = 'python3 "$ROOT/build_bindings.py"'
        bindings_built = build_script.index(binding_build)

        self.assertLess(config_created, config_exported)
        self.assertIn(
            'PYTHON="$TOOL_VENV/bin/python" \\',
            build_script[config_exported:sdists_fetched],
        )
        self.assertLess(config_exported, sdists_fetched)
        self.assertLess(sdists_fetched, bindings_built)


class WheelAssemblyTests(unittest.TestCase):
    def test_runtime_package_payload_is_rooted_in_importable_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package = Path(temp_dir)
            (package / "__init__.py").write_text(
                "VERSION = '3.13.3'\n", encoding="utf-8"
            )
            (package / "manifest.json").write_text(
                '{"gdal_release": "3.13.3"}\n', encoding="utf-8"
            )

            payload = assemble_wheels.read_runtime_package(package)

        self.assertEqual(
            set(payload),
            {
                "haste_gdal_runtime/__init__.py",
                "haste_gdal_runtime/manifest.json",
            },
        )
        self.assertIn(b"3.13.3", payload["haste_gdal_runtime/manifest.json"])

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
        self.assertEqual(env["CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED"], "NO")
        self.assertEqual(env["GDAL_DISABLE_READDIR_ON_OPEN"], "TRUE")
        self.assertEqual(env["GDAL_DATA"], str(rt.GDAL_DATA_DIR))

    def test_skip_list_merges_with_existing(self):
        policy = rt.Policy("3.13.3", allowed_drivers=frozenset({"GTiff"}))
        env = {"GDAL_SKIP": "PNG, Foo"}
        rt.configure(policy, environ=env, manifest=MANIFEST)
        self.assertEqual(
            sorted(env["GDAL_SKIP"].split(",")),
            [
                "COG",
                "Foo",
                "GNMDatabase",
                "GNMFile",
                "GPKG",
                "MEM",
                "PNG",
                "VRT",
            ],
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
                    "GNMDatabase",
                    "GNMFile",
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
                    "GNMDatabase",
                    "GNMFile",
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
