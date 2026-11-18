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
        self.locked = {asset["name"]: asset["digest"] for asset in self.assets}
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
        guard.validate_pins(
            self.requirements, 1, 2, 1, self.locked, self.assets
        )

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
                    self.locked,
                    self.assets,
                )

    def test_missing_or_unverified_asset_is_rejected(self):
        for assets in (
            self.assets[:-1],
            [{**asset, "digest": None} for asset in self.assets],
        ):
            with self.subTest(assets=assets), self.assertRaises(ValueError):
                guard.validate_pins(
                    self.requirements, 1, 2, 1, self.locked, assets
                )

    def test_changed_release_digest_is_rejected(self):
        assets = [dict(asset) for asset in self.assets]
        assets[0]["digest"] = "sha256:" + "b" * 64
        with self.assertRaises(ValueError):
            guard.validate_pins(
                self.requirements, 1, 2, 1, self.locked, assets
            )

    def test_asset_lock_requires_exactly_six_valid_distinct_wheels(self):
        lines = [
            f"{digest.removeprefix('sha256:')} {name}"
            for name, digest in self.locked.items()
        ]
        self.assertEqual(guard.locked_assets("\n".join(lines), 1), self.locked)
        for invalid in (
            lines[:-1],
            [*lines, lines[0]],
            [lines[0].replace("a" * 64, "z" * 64), *lines[1:]],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                guard.locked_assets("\n".join(invalid), 1)

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
                guard.validate_pins(
                    requirements, 1, 2, 1, self.locked, self.assets
                )


if __name__ == "__main__":
    unittest.main()
