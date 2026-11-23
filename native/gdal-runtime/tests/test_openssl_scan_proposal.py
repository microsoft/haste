import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prepare_openssl_scan_proposal as proposal  # noqa: E402
from apply_openssl_patches import PATCH_LOCK, load_patches  # noqa: E402


class OpenSslScanProposalTests(unittest.TestCase):
    def setUp(self):
        self.patches = load_patches(PATCH_LOCK)
        self.manifest = {"openssl_patches": self.patches}
        self.bom = {
            "metadata": {
                "component": {"version": "3.13.3+haste.2"},
                "properties": [
                    {
                        "name": "gdal_runtime.openssl_patches",
                        "value": json.dumps(self.patches),
                    }
                ],
            },
            "components": [
                {
                    "name": "openssl",
                    "version": "3.5.9",
                    "purl": "pkg:generic/openssl@3.5.9",
                    "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
                }
            ],
        }

    def build(self, manifest=None, wheel_manifest=None, bom=None, build="2"):
        return proposal.build_proposal(
            self.manifest if manifest is None else manifest,
            self.manifest if wheel_manifest is None else wheel_manifest,
            self.bom if bom is None else bom,
            self.patches,
            "3.13.3+haste.2",
            build,
            "3.5.9",
            "a" * 64,
            "ignore:\n  - vulnerability: CVE-2026-85091\n",
        )

    def test_proposal_only_adds_five_specific_openssl_rules(self):
        text = self.build()
        self.assertIn("REVIEW-ONLY", text)
        self.assertEqual(text.count("name: openssl"), 5)
        self.assertEqual(text.count("version: 3.5.9"), 5)
        self.assertIn("CVE-2026-85091", text)
        self.assertNotIn("CVE-2026-119586", text)

    def test_unpatched_or_wrong_build_cannot_generate_proposal(self):
        for kwargs in (
            {"manifest": {}},
            {"wheel_manifest": {}},
            {"build": "1"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.build(**kwargs)

    def test_mismatched_sbom_patch_or_source_is_rejected(self):
        for mutation in ("patches", "source", "version"):
            bom = copy.deepcopy(self.bom)
            if mutation == "patches":
                bom["metadata"]["properties"][0]["value"] = "[]"
            elif mutation == "source":
                bom["components"][0]["hashes"][0]["content"] = "b" * 64
            else:
                bom["metadata"]["component"]["version"] = "3.13.3+haste.1"
            with self.subTest(mutation=mutation), self.assertRaises(
                ValueError
            ):
                self.build(bom=bom)

    def test_comparison_rejects_suppressing_sqlite_or_other_findings(self):
        def match(identifier, purl, cve):
            return {
                "artifact": {"id": identifier, "purl": purl},
                "vulnerability": {"id": cve},
            }

        fixes = [
            match("openssl", "pkg:generic/openssl@3.5.9", cve)
            for cve in proposal.FIXES
        ]
        sqlite = match(
            "sqlite", "pkg:generic/sqlite@3.54.1", "CVE-2026-119586"
        )
        baseline = {"matches": [*fixes, sqlite]}
        candidate = {"matches": [sqlite], "ignoredMatches": fixes}
        proposal.compare_scans(baseline, candidate)
        for invalid in (
            {"matches": [], "ignoredMatches": [*fixes, sqlite]},
            {"matches": [sqlite], "ignoredMatches": fixes[:-1]},
            {"matches": [*fixes, sqlite], "ignoredMatches": []},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                proposal.compare_scans(baseline, invalid)

    def test_proposal_does_not_change_the_blocking_security_scan(self):
        workflow = (
            ROOT.parents[1] / ".github/workflows/gdal-runtime-build.yml"
        ).read_text(encoding="utf-8")
        blocking = workflow.split("  vulnerability-scan:", 1)[1].split(
            "  openssl-scan-proposal:", 1
        )[0]
        shadow = workflow.split("  openssl-scan-proposal:", 1)[1].split(
            "  training-base-smoke:", 1
        )[0]
        self.assertEqual(blocking.count("fail-build: true"), 1)
        self.assertIn("prepare_candidate_scan.py", blocking)
        self.assertIn("--fail-on medium", blocking)
        self.assertIn("--compare-baseline", blocking)
        self.assertNotIn("openssl-proposal.yaml", blocking)
        self.assertIn("fail-build: false", shadow)
        self.assertIn('grype-version: "v0.97.1"', shadow)
        self.assertIn("--compare-baseline", shadow)
        self.assertIn("--compare-proposal", shadow)


if __name__ == "__main__":
    unittest.main()
