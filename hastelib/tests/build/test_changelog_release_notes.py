# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

from changelog_release_notes import absolutize_links, extract  # noqa: E402

SAMPLE = """# Changelog

## [Unreleased]

### Added
- Something in flight

---

## [v2.0.0] — Big release

### Added
- A feature

---

## [v1.4.1] — Initial public release

### Added
- The first thing
"""


class ExtractTests(unittest.TestCase):
    def test_extracts_section_without_bleeding_into_the_next(self):
        notes = extract(SAMPLE, "v2.0.0")

        self.assertEqual("v2.0.0", notes.version)
        self.assertEqual("Big release", notes.title)
        self.assertEqual("### Added\n- A feature", notes.body)
        self.assertNotIn("first thing", notes.body)

    def test_extracts_final_section_at_end_of_file(self):
        notes = extract(SAMPLE, "v1.4.1")

        self.assertEqual("### Added\n- The first thing", notes.body)

    def test_version_lookup_ignores_the_v_prefix(self):
        self.assertEqual(
            extract(SAMPLE, "2.0.0").body, extract(SAMPLE, "v2.0.0").body
        )

    def test_display_title_falls_back_to_the_bare_version(self):
        notes = extract(SAMPLE, "Unreleased")

        self.assertEqual("Unreleased", notes.display_title)

    def test_missing_version_reports_the_available_sections(self):
        with self.assertRaises(ValueError) as caught:
            extract(SAMPLE, "v9.9.9")

        self.assertIn("v2.0.0", str(caught.exception))

    def test_empty_section_is_rejected(self):
        with self.assertRaises(ValueError):
            extract("## [v1.0.0]\n\n---\n\n## [v0.9.0]\n\n- x\n", "v1.0.0")


class LinkRewriteTests(unittest.TestCase):
    def test_relative_links_become_permalinks_at_the_ref(self):
        body = "See [config](docs/configuration.md) and [dir](spec/features/)."

        result = absolutize_links(body, "v2.0.0")

        self.assertIn(
            "https://github.com/microsoft/haste/blob/v2.0.0/"
            "docs/configuration.md",
            result,
        )
        self.assertIn(
            "https://github.com/microsoft/haste/tree/v2.0.0/spec/features",
            result,
        )

    def test_relative_link_anchors_are_preserved(self):
        result = absolutize_links("[x](docs/configuration.md#pools)", "v2.0.0")

        self.assertTrue(result.endswith("/docs/configuration.md#pools)"))

    def test_absolute_and_anchor_links_are_left_alone(self):
        body = (
            "[pr](https://github.com/microsoft/haste/pull/1) "
            "[top](#changelog) [mail](mailto:a@b.com)"
        )

        self.assertEqual(body, absolutize_links(body, "v2.0.0"))


class RealChangelogTests(unittest.TestCase):
    """Guard the actual file the release workflow reads."""

    def setUp(self):
        self.changelog = (REPO_ROOT / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )

    def test_every_version_section_extracts_with_a_title_and_body(self):
        versions = re.findall(
            r"^## \[(v\d+\.\d+\.\d+)\]", self.changelog, flags=re.MULTILINE
        )
        self.assertGreater(len(versions), 0)

        for version in versions:
            with self.subTest(version=version):
                notes = extract(self.changelog, version)
                self.assertTrue(notes.title, "release title is required")
                self.assertTrue(notes.body.strip())
                self.assertNotIn("## [", notes.body)

    def test_extracted_notes_contain_no_repo_relative_links(self):
        versions = re.findall(
            r"^## \[(v\d+\.\d+\.\d+)\]", self.changelog, flags=re.MULTILINE
        )

        for version in versions:
            with self.subTest(version=version):
                body = absolutize_links(
                    extract(self.changelog, version).body, version
                )
                leftovers = [
                    target
                    for target in re.findall(r"\]\(([^)]+)\)", body)
                    if not target.startswith(("http", "#", "mailto:"))
                ]
                self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()
