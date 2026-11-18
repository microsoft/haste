import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_published_runtime as guard  # noqa: E402


class PublishedRuntimeTests(unittest.TestCase):
    def setUp(self):
        prefix = (
            "https://github.com/microsoft/haste/releases/download/"
            "haste-binaries/"
        )
        self.filenames = {
            name: f"{name.replace('-', '_')}-1.0+haste.1-py3-none-any.whl"
            for name in guard.WHEELS
        }
        self.assets = [
            {"name": name, "state": "uploaded", "digest": "sha256:" + "a" * 64}
            for name in self.filenames.values()
        ]
        self.requirements = {
            path: "\n".join(
                f"{name} @ {prefix}{self.filenames[name]}"
                for name in (
                    {"haste-gdal-runtime", "rasterio"}
                    if path == "api/titilerfuncapi/requirements.txt"
                    else guard.WHEELS
                )
            )
            for path in guard.RUNTIME_FILES
        }

    def test_candidate_can_advance_while_published_assets_remain_available(
        self,
    ):
        guard.validate_pins(self.requirements, 1, 2, 1, self.assets)

    def test_published_and_candidate_downgrades_are_rejected(self):
        for published, candidate, baseline in ((1, 2, 2), (2, 1, 1)):
            with self.subTest(published=published), self.assertRaises(
                ValueError
            ):
                guard.validate_pins(
                    self.requirements,
                    published,
                    candidate,
                    baseline,
                    self.assets,
                )

    def test_missing_or_unverified_asset_is_rejected(self):
        for assets in (
            self.assets[:-1],
            [{**asset, "digest": None} for asset in self.assets],
        ):
            with self.subTest(assets=assets), self.assertRaises(ValueError):
                guard.validate_pins(self.requirements, 1, 2, 1, assets)

    def test_foreign_or_mixed_runtime_url_is_rejected(self):
        path = guard.RUNTIME_FILES[0]
        for replacement in (
            ("github.com", "example.com"),
            ("+haste.1-", "+haste.2-"),
        ):
            requirements = dict(self.requirements)
            requirements[path] = requirements[path].replace(*replacement)
            with self.subTest(replacement=replacement), self.assertRaises(
                ValueError
            ):
                guard.validate_pins(requirements, 1, 2, 1, self.assets)


if __name__ == "__main__":
    unittest.main()
