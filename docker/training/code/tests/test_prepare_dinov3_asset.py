# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Offline recipe emission with generated assets, never public-model acceptance."""

import base64
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import torch
from pydantic import ValidationError
from transformers import DINOv3ViTConfig

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "validation"))
sys.path.insert(0, str(ROOT / "hastelib" / "src"))
sys.path.insert(0, str(ROOT / "docker" / "training" / "code"))

import prepare_dinov3_asset as preparation  # noqa: E402
from bda.dinov3_upernet import DINOv3UPerNet  # noqa: E402
from hastegeo.core.models.training import CatalogModel  # noqa: E402


class PrepareAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(2)
        cls.config_dict = DINOv3ViTConfig(
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=4,
            num_attention_heads=4,
            num_register_tokens=4,
        ).to_dict()
        torch.manual_seed(43)
        model = DINOv3UPerNet("dinov3_vits16", cls.config_dict).eval()
        cls.state = {
            "model." + key: value for key, value in model.state_dict().items()
        }

    @classmethod
    def tearDownClass(cls):
        del cls.state
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.checkpoint = self.root / "fixture.ckpt"
        self.config = self.root / "config.json"
        self.provenance = self.root / "provenance.json"
        torch.save(
            {
                "hyper_parameters": {
                    "model": "upernet",
                    "backbone": "dinov3_vits16",
                    "in_channels": 3,
                    "num_classes": 3,
                },
                "state_dict": self.state,
            },
            self.checkpoint,
        )
        content = self.checkpoint.read_bytes()
        self.checkpoint_sha = hashlib.sha256(content).hexdigest()
        # Only these generated fixtures are substituted for the CLI's fixed
        # authorized asset identity. There is no runtime "trust any file" flag.
        identity = mock.patch.multiple(
            preparation,
            SHA256=self.checkpoint_sha,
            SIZE=len(content),
            MD5=base64.b64encode(
                hashlib.md5(content, usedforsecurity=False).digest()
            ).decode(),
        )
        identity.start()
        self.addCleanup(identity.stop)
        self.config.write_text(json.dumps(self.config_dict))
        self.proof = {
            "schemaVersion": 1,
            "checkpointSha256": self.checkpoint_sha,
            "backboneConfigSha256": hashlib.sha256(
                self.config.read_bytes()
            ).hexdigest(),
            "backboneConfigSource": "fixture://generated-config",
            "labelGrouping": "any",
            "labelMapping": [0, 1, 2, 2, 2],
            "labelGroupingSource": "fixture://generated-label-map",
        }
        self.write_proof()

    def write_proof(self):
        self.provenance.write_text(json.dumps(self.proof))

    def prepare(self):
        return preparation.prepare_recipe(
            self.checkpoint,
            self.config,
            self.provenance,
            "fixture-operator",
            name="fixture-only",
            device="cpu",
            patch_size=32,
            padding=8,
        )

    def test_native_strict_acceptance_emits_valid_deterministic_recipe(self):
        with mock.patch(
            "socket.socket.connect", side_effect=AssertionError("network")
        ):
            first = self.prepare()
            second = self.prepare()
        self.assertNotIn("status", first, first)
        entry = CatalogModel.model_validate(first)
        self.assertEqual(first, second)
        self.assertEqual(entry.capabilities, ["inference"])
        self.assertEqual(entry.inferenceSpec.adapter, "dinov3_upernet")
        self.assertEqual(
            entry.inferenceSpec.checkpointSha256, self.checkpoint_sha
        )
        self.assertEqual(
            entry.inferenceSpec.backboneConfigSha256,
            self.proof["backboneConfigSha256"],
        )
        self.assertEqual(entry.inferenceSpec.patchSize, 32)
        self.assertEqual(entry.inferenceSpec.padding, 8)
        self.assertEqual(
            entry.inferenceSpec.normalizationMeans, [0.485, 0.456, 0.406]
        )
        self.assertEqual(
            entry.checkpointFilePath,
            f"model-catalog/assets/{self.checkpoint_sha}/model.ckpt",
        )
        validation = entry.additionalInfo["assetValidation"]
        self.assertTrue(validation["strictStateDict"])
        self.assertTrue(validation["finiteForward"])
        self.assertEqual(validation["forwardShape"], [1, 3, 32, 32])
        self.assertEqual(validation["backboneConfig"]["hidden_size"], 32)
        self.assertIn("backboneLicense", entry.additionalInfo)
        self.assertEqual(entry.additionalInfo["sourceCode"]["license"], "MIT")
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_missing_authorized_inputs_yield_non_importable_diagnostic(self):
        with mock.patch.object(preparation, "validate_model") as validate:
            document = preparation.prepare_recipe(self.checkpoint)
        validate.assert_not_called()
        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["reason"], "missing_inputs")
        self.assertIn("authorized_backbone_config", document["detail"])
        self.assertIn("training_and_config_provenance", document["detail"])
        self.assertNotIn("inferenceSpec", document)
        with self.assertRaises(ValidationError):
            CatalogModel.model_validate(document)

    def test_grouping_provenance_cannot_be_guessed_or_reused_for_other_assets(
        self,
    ):
        for key, value in [
            ("labelGroupingSource", ""),
            ("backboneConfigSource", ""),
            ("labelMapping", [0, 1, 1, 1, 2]),
            ("labelGrouping", "destroyed"),
            ("checkpointSha256", "a" * 64),
            ("backboneConfigSha256", "b" * 64),
        ]:
            with self.subTest(key=key):
                changed = dict(self.proof, **{key: value})
                self.provenance.write_text(json.dumps(changed))
                with mock.patch.object(
                    preparation, "validate_model"
                ) as validate:
                    document = self.prepare()
                validate.assert_not_called()
                self.assertEqual(document["status"], "blocked")
                self.assertEqual(
                    document["reason"], "config_and_provenance_validation"
                )

    def test_changed_backbone_fails_real_strict_state_loading(self):
        config = dict(self.config_dict, hidden_size=64)
        self.config.write_text(json.dumps(config))
        self.proof["backboneConfigSha256"] = hashlib.sha256(
            self.config.read_bytes()
        ).hexdigest()
        self.write_proof()
        document = self.prepare()
        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["reason"], "strict_model_validation")
        self.assertIn("size mismatch", document["detail"])
        self.assertNotIn("inferenceSpec", document)

    def test_checkpoint_digest_checked_before_deserialization(self):
        with mock.patch.object(preparation, "SHA256", "0" * 64):
            with mock.patch.object(torch, "load") as load:
                document = self.prepare()
        load.assert_not_called()
        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["reason"], "checkpoint_validation")

    def test_restricted_inspection_rejects_affected_torch_before_loading(self):
        for version in ("2.5.1", "2.6.0", "2.8.0+cu128", "2.9.1", "2.10.0rc1"):
            with self.subTest(version=version), mock.patch.object(
                torch, "__version__", version
            ), mock.patch.object(torch, "load") as load:
                document = self.prepare()
            load.assert_not_called()
            self.assertEqual(document["status"], "blocked")
            self.assertIn("torch>=2.10.0", document["detail"])
            self.assertNotIn("inferenceSpec", document)

    def test_validation_failure_never_emits_recipe(self):
        with mock.patch.object(
            preparation,
            "validate_model",
            side_effect=ValueError("Model returned non-finite logits"),
        ):
            document = self.prepare()
        self.assertEqual(document["status"], "blocked")
        self.assertNotIn("inferenceSpec", document)

    def test_recipe_output_is_scoped_and_does_not_clobber(self):
        document = self.prepare()
        path = self.root / "recipe.json"
        preparation.write_recipe(path, document, self.root)
        before = path.stat().st_mtime_ns
        preparation.write_recipe(path, document, self.root)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(json.loads(path.read_bytes()), document)
        with self.assertRaises(FileExistsError):
            preparation.write_recipe(
                path, dict(document, baseModelName="different"), self.root
            )
        with self.assertRaises(ValueError):
            preparation.write_recipe(
                self.root.parent / "not-scoped.json", document, self.root
            )
        with self.assertRaises(ValueError):
            preparation.write_recipe(
                path, preparation.blocked("missing", "config"), self.root
            )

    def test_cli_blocked_stdout_is_one_json_and_no_recipe_file(self):
        output = io.StringIO()
        path = self.root / "must-not-exist.json"
        with mock.patch.object(
            preparation, "stage_checkpoint", return_value=self.checkpoint
        ), mock.patch("sys.stdout", output):
            code = preparation.main(["--recipe-output", str(path)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
        self.assertFalse(path.exists())

    def test_cli_success_stdout_matches_written_catalog_model(self):
        output = io.StringIO()
        path = self.root / "recipe.json"
        with mock.patch.object(
            preparation, "stage_checkpoint", return_value=self.checkpoint
        ), mock.patch.object(
            preparation, "asset_directory", return_value=self.root
        ), mock.patch(
            "sys.stdout", output
        ):
            code = preparation.main(
                [
                    "--backbone-config",
                    str(self.config),
                    "--provenance",
                    str(self.provenance),
                    "--catalogued-by",
                    "fixture-operator",
                    "--name",
                    "fixture-only",
                    "--device",
                    "cpu",
                    "--patch-size",
                    "32",
                    "--padding",
                    "8",
                    "--recipe-output",
                    str(path),
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(
            json.loads(output.getvalue()), json.loads(path.read_bytes())
        )
        CatalogModel.model_validate_json(output.getvalue())

    def test_authenticated_config_fetch_uses_resolved_commit_and_full_export(
        self,
    ):
        revision = "a" * 40

        def download(**kwargs):
            self.assertIs(kwargs["token"], True)
            self.assertEqual(kwargs["revision"], revision)
            self.assertEqual(
                kwargs["repo_id"], preparation.BACKBONE_REPOSITORY
            )
            directory = kwargs["local_dir"]
            directory.mkdir(parents=True)
            official = directory / "config.json"
            official.write_text(json.dumps(self.config_dict))
            return str(official)

        with mock.patch("huggingface_hub.HfApi") as api, mock.patch(
            "huggingface_hub.hf_hub_download", side_effect=download
        ) as fetch, mock.patch.object(
            preparation, "asset_directory", return_value=self.root
        ):
            api.return_value.model_info.return_value = SimpleNamespace(
                sha=revision
            )
            record = preparation.fetch_backbone_config()
        api.assert_called_once_with(token=True)
        api.return_value.model_info.assert_called_once_with(
            preparation.BACKBONE_REPOSITORY, revision="main"
        )
        fetch.assert_called_once()
        exported, digest = preparation.read_json_asset(
            Path(record["expandedConfigPath"])
        )
        self.assertEqual(record["expandedConfigSha256"], digest)
        self.assertEqual(record["revision"], revision)
        self.assertEqual(exported["num_attention_heads"], 4)
        self.assertEqual(
            exported["rope_theta"], self.config_dict["rope_theta"]
        )
        self.assertEqual(exported["transformers_version"], "5.5.4")
        self.assertNotIn("token", record)

    def test_gated_config_failure_has_no_alternative_download(self):
        with mock.patch("huggingface_hub.HfApi") as api, mock.patch(
            "huggingface_hub.hf_hub_download",
            side_effect=PermissionError("access denied"),
        ) as fetch, mock.patch.object(
            preparation, "asset_directory", return_value=self.root
        ):
            api.return_value.model_info.return_value = SimpleNamespace(
                sha="a" * 40
            )
            with self.assertRaises(PermissionError):
                preparation.fetch_backbone_config()
        fetch.assert_called_once()
        self.assertFalse(list(self.root.rglob("config.expanded.json")))

    def test_run_evidence_preserves_original_vs_tier3_without_home_prefix(
        self,
    ):
        original = "outputs/xview2_dinov3_upernet_any/checkpoints/last.ckpt"
        tier3 = (
            "outputs/xview2_dinov3_upernet_tier3_lr_sweep/run_001/"
            "any/lr_3e-05/checkpoints/last.ckpt"
        )
        for relative in (original, tier3):
            self.assertEqual(
                preparation.relative_run_path("/private/root/" + relative),
                relative,
            )
        self.assertNotEqual(original, tier3)


if __name__ == "__main__":
    unittest.main()
