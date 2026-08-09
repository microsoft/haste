from typing import Callable, Dict, Optional

from ..config import Config
from ..models.publishing import ArtifactKind, ProviderConfigField, ProviderInfo
from .base import PublishingProvider


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot currently accept publishing work."""


class PublishingProviderRegistry:
    """Expose known provider capabilities and lazily resolve implementations."""

    def __init__(
        self,
        config: Optional[Config] = None,
        factories: Optional[
            Dict[str, Callable[[], PublishingProvider]]
        ] = None,
    ) -> None:
        self.config = config or Config()
        self.factories = factories or {}

    def _provider_infos(self) -> Dict[str, ProviderInfo]:
        settings = self.config.publishing_config
        publishing_enabled = settings["publishing_enabled"]
        pc_enabled = settings["pc_provider_enabled"]
        pc_configured = bool(
            settings["pc_geocatalog_url"] and settings["pc_ingestion_source"]
        )
        return {
            "local": ProviderInfo(
                id="local",
                displayName="Local (HASTE storage)",
                description="Immutable copy in HASTE-managed storage",
                isEnabled=publishing_enabled,
                isConfigured=True,
                disabledReason=(
                    None if publishing_enabled else "Publishing is disabled"
                ),
                supportedArtifactKinds=list(ArtifactKind),
            ),
            "planetary_computer": ProviderInfo(
                id="planetary_computer",
                displayName="Planetary Computer",
                description="STAC discovery and vector downloads",
                isEnabled=pc_enabled,
                isConfigured=pc_configured,
                disabledReason=self._pc_disabled_reason(
                    pc_enabled, pc_configured
                ),
                supportedArtifactKinds=[
                    ArtifactKind.GPKG,
                    ArtifactKind.VALID_MASK,
                    ArtifactKind.FOOTPRINTS,
                ],
                requiredSupportingArtifactKinds=[ArtifactKind.VALID_MASK],
                configRequirements=[
                    ProviderConfigField(
                        key="geocatalog_url",
                        label="GeoCatalog URL",
                        required=True,
                    ),
                    ProviderConfigField(
                        key="ingestion_source",
                        label="Ingestion source",
                        required=True,
                    ),
                ],
            ),
        }

    @staticmethod
    def _pc_disabled_reason(enabled: bool, configured: bool) -> Optional[str]:
        if not enabled:
            return "Disabled by the operator"
        if not configured:
            return "Planetary Computer is not configured"
        return None

    def list_infos(self) -> list[ProviderInfo]:
        return list(self._provider_infos().values())

    def get_info(self, provider_id: str) -> ProviderInfo:
        try:
            return self._provider_infos()[provider_id]
        except KeyError as error:
            raise ProviderUnavailableError(
                f"Unknown publishing provider: {provider_id}"
            ) from error

    def resolve(self, provider_id: str) -> PublishingProvider:
        info = self.get_info(provider_id)
        if not info.isEnabled or not info.isConfigured:
            raise ProviderUnavailableError(
                info.disabledReason or "Publishing provider is unavailable"
            )
        factory = self.factories.get(provider_id)
        if factory is None and provider_id == "local":
            from .local_provider import LocalPublishingProvider

            def local_factory() -> PublishingProvider:
                return LocalPublishingProvider(config=self.config)

            factory = local_factory
        if factory is None and provider_id == "planetary_computer":
            from .planetary_computer_provider import (
                PlanetaryComputerPublishingProvider,
            )

            def planetary_computer_factory() -> PublishingProvider:
                return PlanetaryComputerPublishingProvider(config=self.config)

            factory = planetary_computer_factory
        if factory is None:
            raise ProviderUnavailableError(
                f"No implementation registered for provider: {provider_id}"
            )
        return factory()
