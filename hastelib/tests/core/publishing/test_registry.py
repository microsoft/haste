import unittest
from unittest.mock import patch

from hastegeo.core.models.publishing import ArtifactKind
from hastegeo.core.publishing.registry import (
    ProviderUnavailableError,
    PublishingProviderRegistry,
)


class FakeConfig:
    def __init__(
        self, enabled: bool, pc_enabled: bool, configured: bool
    ) -> None:
        self.publishing_config = {
            "publishing_enabled": enabled,
            "pc_provider_enabled": pc_enabled,
            "pc_geocatalog_url": "https://catalog" if configured else None,
            "pc_ingestion_source": "source" if configured else None,
        }


class TestPublishingProviderRegistry(unittest.TestCase):
    def test_lists_all_known_provider_descriptors(self) -> None:
        registry = PublishingProviderRegistry(
            config=FakeConfig(True, False, False)
        )

        infos = registry.list_infos()

        self.assertEqual(
            [info.id for info in infos], ["local", "planetary_computer"]
        )

    def test_unknown_provider_is_rejected(self) -> None:
        registry = PublishingProviderRegistry(
            config=FakeConfig(True, False, False)
        )

        with self.assertRaisesRegex(ProviderUnavailableError, "Unknown"):
            registry.get_info("unknown")

    def test_default_local_factory_is_loaded_lazily(self) -> None:
        provider = object()
        registry = PublishingProviderRegistry(
            config=FakeConfig(True, False, False)
        )

        with patch(
            "hastegeo.core.publishing.local_provider.LocalPublishingProvider",
            return_value=provider,
        ) as provider_type:
            resolved = registry.resolve("local")

        self.assertIs(resolved, provider)
        provider_type.assert_called_once_with(config=registry.config)

    def test_disabled_pc_descriptor_does_not_invoke_factory(self) -> None:
        invoked = []
        registry = PublishingProviderRegistry(
            config=FakeConfig(True, False, True),
            factories={"planetary_computer": lambda: invoked.append(True)},
        )

        info = registry.get_info("planetary_computer")

        self.assertFalse(info.isEnabled)
        self.assertTrue(info.isConfigured)
        self.assertEqual(
            info.supportedArtifactKinds,
            [
                ArtifactKind.GPKG,
                ArtifactKind.VALID_MASK,
                ArtifactKind.FOOTPRINTS,
            ],
        )
        with self.assertRaises(ProviderUnavailableError):
            registry.resolve("planetary_computer")
        self.assertEqual(invoked, [])

    def test_enabled_unconfigured_pc_is_independently_disabled(self) -> None:
        registry = PublishingProviderRegistry(
            config=FakeConfig(True, True, False)
        )

        info = registry.get_info("planetary_computer")

        self.assertTrue(info.isEnabled)
        self.assertFalse(info.isConfigured)

    def test_enabled_configured_pc_invokes_injected_factory(self) -> None:
        provider = object()
        registry = PublishingProviderRegistry(
            config=FakeConfig(True, True, True),
            factories={"planetary_computer": lambda: provider},
        )

        resolved = registry.resolve("planetary_computer")

        self.assertIs(resolved, provider)


if __name__ == "__main__":
    unittest.main()
