# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


class TestTransformerInferenceImageWiring(unittest.TestCase):
    def test_default_training_target_does_not_install_transformer_dependencies(
        self,
    ) -> None:
        dockerfile = (ROOT / "docker/training/Dockerfile").read_text()
        stages = [
            line
            for line in dockerfile.splitlines()
            if line.startswith("FROM ")
        ]
        self.assertEqual(stages[-1], "FROM training-runtime AS runtime")
        self.assertIn(
            "FROM training-runtime AS transformerinference-runtime", stages
        )
        self.assertLess(
            dockerfile.index(
                "FROM training-runtime AS transformerinference-runtime"
            ),
            dockerfile.index("-r /tmp/transformerinference-requirements.txt"),
        )
        legacy = (ROOT / "docker/training/env/env.yml").read_text()
        self.assertIn("torch==2.5.1+cu124", legacy)
        self.assertIn("torchvision==0.20.1+cu124", legacy)

    def test_fixed_loader_wheels_are_integrity_pinned_for_the_image_python(
        self,
    ) -> None:
        requirements = (
            ROOT / "docker/transformerinference/requirements.txt"
        ).read_text()
        self.assertIn("torch-2.10.0%2Bcu128-cp310", requirements)
        self.assertIn("torchvision-0.25.0%2Bcu128-cp310", requirements)
        self.assertEqual(requirements.count("#sha256="), 2)
        self.assertIn("transformers==5.5.4", requirements)
        legacy = yaml.safe_load(
            (ROOT / "docker/training/env/env.yml").read_text()
        )
        self.assertIn("python=3.10", legacy["dependencies"])

    def test_compose_api_and_queue_agree_on_the_separate_image(self) -> None:
        services = yaml.safe_load(
            (ROOT / "docker/docker-compose.yml").read_text()
        )["services"]
        self.assertEqual(
            services["transformerinference_image"]["build"]["target"],
            "transformerinference-runtime",
        )
        for service in ("hastefuncapi", "hastefuncqueues"):
            with self.subTest(service=service):
                settings = services[service]["environment"]
                self.assertEqual(settings["RUNNER_TYPE"], "local")
                self.assertEqual(
                    settings["AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE"],
                    "haste-transformerinference:latest",
                )
                self.assertEqual(
                    settings["AZURE_BATCH_DOCKER_IMAGE"],
                    "haste-training:latest",
                )
                self.assertIn(
                    "azurite-data:/shared/azurite",
                    services[service]["volumes"],
                )

    def test_rc_images_and_deployment_use_the_matching_transformer_tag(
        self,
    ) -> None:
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/hastegeo-publish.yml").read_text()
        )
        images = workflow["jobs"]["build-rc-images"]["strategy"]["matrix"][
            "include"
        ]
        self.assertIn(
            {
                "image_dir": "transformerinference",
                "image_name": "hastetransformerinference",
            },
            images,
        )
        deploy = (ROOT / ".github/workflows/deploy-apps.yml").read_text()
        self.assertIn('"$TRANSFORMER_INFERENCE_TAG" != "$VERSION"', deploy)
        self.assertIn(
            "TRANSFORMER_INFERENCE_IMAGE_TAG: ${{ steps.artifacts.outputs.transformer_inference_tag }}",
            deploy,
        )

    def test_build_and_deploy_entrypoints_use_the_generic_image_name(
        self,
    ) -> None:
        build = (ROOT / ".github/scripts/build_and_push_images.sh").read_text()
        self.assertIn("training|transformerinference|imageryprep|all)", build)
        self.assertIn('if [[ "$image_dir" == "transformerinference" ]]', build)
        self.assertIn(
            "target_args=(--target transformerinference-runtime)", build
        )
        workflow = (
            ROOT / ".github/workflows/docker-build-and-push.yml"
        ).read_text()
        self.assertIn("'docker/transformerinference/**'", workflow)
        self.assertIn("image_dir: transformerinference", workflow)
        self.assertIn("--target transformerinference-runtime", workflow)
        deploy = (ROOT / ".github/scripts/deploy_apps.sh").read_text()
        self.assertIn(
            'TRANSFORMER_INFERENCE_DOCKER_IMAGE="hastetransformerinference:',
            deploy,
        )
        self.assertIn(
            "AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE=${ACR_NAME}.azurecr.io/${TRANSFORMER_INFERENCE_DOCKER_IMAGE}",
            deploy,
        )
