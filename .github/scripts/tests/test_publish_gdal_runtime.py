import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from publish_gdal_runtime import (  # noqa: E402
    EXPECTED_DISTRIBUTIONS,
    _sha256,
    publish_bundle,
    validate_bundle,
)


class PublishGdalRuntimeTests(unittest.TestCase):
    def _bundle_directory(self, root: Path) -> Path:
        directory = root / "dist"
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "gdal_release": "3.13.3",
                    "binding_versions": {
                        "osgeo.gdal": "3.13.3",
                        "rasterio": "1.4.4",
                        "fiona": "1.10.1",
                        "pyogrio": "0.13.0",
                        "pyproj": "3.7.2",
                    },
                }
            ),
            encoding="utf-8",
        )
        source_lock_path = root / "sources.lock"
        patcher = mock.patch(
            "publish_gdal_runtime.SOURCE_LOCK_PATH", source_lock_path
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        source_lock_path.write_text(
            "HASTE_GDAL_BUILD 2\n"
            "gdal 3.13.3 https://example.test/gdal.tar.gz "
            + "a" * 64
            + "\nproj 9.8.1 https://example.test/proj.tar.gz "
            + "b" * 64
            + "\n",
            encoding="utf-8",
        )
        (directory / "bom.cdx.json").write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.6",
                    "components": [
                        {
                            "name": name,
                            "licenses": [{"license": {"id": "MIT"}}],
                        }
                        for name in sorted(EXPECTED_DISTRIBUTIONS)
                    ]
                    + [
                        {
                            "name": "gdal",
                            "version": "3.13.3",
                            "purl": "pkg:generic/gdal@3.13.3",
                            "licenses": [{"license": {"id": "MIT"}}],
                        },
                        {
                            "name": "proj",
                            "version": "9.8.1",
                            "purl": "pkg:generic/proj@9.8.1",
                            "licenses": [{"license": {"id": "MIT"}}],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (directory / "THIRD_PARTY_NOTICES.txt").write_text(
            "All license texts included.\n",
            encoding="utf-8",
        )

        versions = {
            "haste-gdal-runtime": "3.13.3+haste.2",
            "gdal": "3.13.3+haste.2",
            "rasterio": "1.4.4+haste.2",
            "fiona": "1.10.1+haste.2",
            "pyogrio": "0.13.0+haste.2",
            "pyproj": "3.7.2+haste.2",
        }
        for name in sorted(EXPECTED_DISTRIBUTIONS):
            normalized = name.replace("-", "_")
            tag = (
                "py3-none-manylinux_2_28_x86_64"
                if name == "haste-gdal-runtime"
                else "cp311-cp311-manylinux_2_28_x86_64"
            )
            path = directory / f"{normalized}-{versions[name]}-{tag}.whl"
            requires = (
                ""
                if name == "haste-gdal-runtime"
                else "Requires-Dist: haste-gdal-runtime==" "3.13.3+haste.2\n"
            )
            license_field = (
                "License-Expression: MIT\n"
                if name == "haste-gdal-runtime"
                else "License: MIT\n"
            )
            metadata = (
                "Metadata-Version: 2.1\n"
                f"Name: {name}\n"
                f"Version: {versions[name]}\n"
                f"{license_field}"
                f"{requires}\n"
            )
            with zipfile.ZipFile(path, "w") as wheel:
                wheel.writestr(f"{normalized}.dist-info/METADATA", metadata)
                wheel.writestr(
                    f"{normalized}.dist-info/WHEEL",
                    f"Wheel-Version: 1.0\nTag: {tag}\n",
                )

        assets = [
            path for path in directory.iterdir() if path.name != "SHA256SUMS"
        ]
        checksums = "\n".join(
            f"{_sha256(path)}  {path.name}" for path in sorted(assets)
        )
        (directory / "SHA256SUMS").write_text(
            checksums + "\n", encoding="utf-8"
        )
        return directory

    def test_validates_exact_bundle_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = validate_bundle(self._bundle_directory(Path(temp_dir)))

        self.assertEqual(bundle.gdal_version, "3.13.3")
        self.assertEqual(bundle.runtime_version, "3.13.3+haste.2")
        self.assertEqual(len(bundle.assets), 10)

    def test_rejects_notice_items_marked_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = self._bundle_directory(Path(temp_dir))
            (directory / "THIRD_PARTY_NOTICES.txt").write_text(
                "License review required.\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "marked for review"):
                validate_bundle(directory)

    def test_rejects_unlicensed_sbom_component(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = self._bundle_directory(Path(temp_dir))
            bom_path = directory / "bom.cdx.json"
            bom = json.loads(bom_path.read_text(encoding="utf-8"))
            bom["components"][0].pop("licenses")
            bom_path.write_text(json.dumps(bom), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lack license metadata"):
                validate_bundle(directory)

    def test_rejects_sbom_missing_locked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = self._bundle_directory(Path(temp_dir))
            bom_path = directory / "bom.cdx.json"
            bom = json.loads(bom_path.read_text(encoding="utf-8"))
            bom["components"] = [
                component
                for component in bom["components"]
                if component.get("name") != "proj"
            ]
            bom_path.write_text(json.dumps(bom), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sources.lock"):
                validate_bundle(directory)

    def test_rejects_unexpected_native_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = self._bundle_directory(Path(temp_dir))
            bom_path = directory / "bom.cdx.json"
            bom = json.loads(bom_path.read_text(encoding="utf-8"))
            bom["components"].append(
                {
                    "name": "unlocked-native",
                    "version": "1.0",
                    "purl": "pkg:generic/unlocked-native@1.0",
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            )
            bom_path.write_text(json.dumps(bom), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "unexpected unlocked-native"
            ):
                validate_bundle(directory)

    def test_rejects_manifest_binding_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = self._bundle_directory(Path(temp_dir))
            manifest_path = directory / "manifest.json"
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            manifest["binding_versions"]["fiona"] = "1.10.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError, "binding versions do not match"
            ):
                validate_bundle(directory)

    def test_accepts_folded_runtime_dependency_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = self._bundle_directory(Path(temp_dir))
            wheel_path = next(
                path
                for path in directory.glob("*.whl")
                if "fiona-" in path.name
            )
            with zipfile.ZipFile(wheel_path, "r") as source:
                contents = {
                    name: source.read(name) for name in source.namelist()
                }
            metadata_path = next(
                name
                for name in contents
                if name.endswith(".dist-info/METADATA")
            )
            metadata = contents[metadata_path].decode("utf-8")
            metadata = metadata.replace(
                "Requires-Dist: haste-gdal-runtime==3.13.3+haste.2",
                "Requires-Dist: haste-gdal-runtime==\n 3.13.3+haste.2",
            )
            contents[metadata_path] = metadata.encode("utf-8")
            with zipfile.ZipFile(wheel_path, "w") as output:
                for name, content in contents.items():
                    output.writestr(name, content)
            checksum_file = directory / "SHA256SUMS"
            checksums = []
            for line in checksum_file.read_text(encoding="utf-8").splitlines():
                _, asset_name = line.split("  ", 1)
                checksums.append(
                    f"{_sha256(directory / asset_name)}  {asset_name}"
                )
            checksum_file.write_text(
                "\n".join(checksums) + "\n", encoding="utf-8"
            )

            bundle = validate_bundle(directory)

        self.assertEqual(bundle.runtime_version, "3.13.3+haste.2")

    def test_rejects_overwrite_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = validate_bundle(self._bundle_directory(Path(temp_dir)))
            runner = mock.Mock()
            with self.assertRaisesRegex(ValueError, "will not be overwritten"):
                publish_bundle(
                    bundle,
                    runner=runner,
                    asset_lister=lambda: [bundle.assets[0].name],
                )

        runner.assert_not_called()

    def test_publishes_and_verifies_all_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = validate_bundle(self._bundle_directory(Path(temp_dir)))
            listed = []

            def list_assets() -> list[str]:
                if not listed:
                    listed.extend(path.name for path in bundle.assets)
                    return []
                return listed

            runner = mock.Mock(return_value="")
            publish_bundle(
                bundle,
                runner=runner,
                asset_lister=list_assets,
            )

        runner.assert_called_once()
        command = runner.call_args.args[0]
        self.assertIn("haste-binaries", command)
        self.assertIn("--repo", command)
        self.assertEqual(
            len([arg for arg in command if arg.endswith(".whl")]), 6
        )


if __name__ == "__main__":
    unittest.main()
