# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""``RunnerRegistry``: constructs and caches ``ComputeRunner`` adapters.

Replaces ``UnifiedRunner``'s hard-coded two-entry import map
(``azure_batch`` / ``local``) with an explicit registration API plus a lazy
dynamic-import fallback, keyed by ``(backend, profile)`` so more than one
named adapter configuration can coexist (data-model.md's
``backendProfile``).

``azure_batch``, ``local``, and ``azure_ml`` all implement ``ComputeRunner``
now (plan.md Phases 4 and 7, both landed) and are listed in the default map
below. Any adapter that fails to import, fails to construct, or does not
conform to ``ComputeRunner`` raises a classified
``BackendConfigurationError`` rather than a raw ``ImportError``/provider-SDK
exception leaking out, so a misconfigured or unavailable backend is
diagnosable at the same boundary regardless of cause — this also means a
future backend added here with a bug in its own construction fails the same
way, not just a not-yet-implemented one.
"""

import importlib
import threading
from typing import Callable, Dict, Optional, Tuple

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    BackendConfigurationError,
    ComputeBackend,
)
from hastegeo.core.utils.logs import Logger

from .base import ComputeRunner

RunnerFactory = Callable[[], ComputeRunner]

DEFAULT_PROFILE = "default"

# Adapter module/class per backend. All three are implemented and wired
# (plan.md Phases 4 & 7, both landed).
_ADAPTER_MODULE_MAP: Dict[ComputeBackend, Tuple[str, str]] = {
    ComputeBackend.AZURE_BATCH: ("azure_batch", "AzureBatchRunner"),
    ComputeBackend.LOCAL: ("local", "LocalRunner"),
    ComputeBackend.AZURE_ML: ("azure_ml", "AzureMLRunner"),
}


class RunnerRegistry:
    """Constructs and caches ``ComputeRunner`` adapters by backend + profile.

    No adapter module is imported until first requested for a given
    ``(backend, profile)`` key, so a Batch/local-only deployment never pays
    the cost of importing the optional AML SDK (design.md#configuration).
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._factories: Dict[Tuple[ComputeBackend, str], RunnerFactory] = {}
        self._instances: Dict[Tuple[ComputeBackend, str], ComputeRunner] = {}
        self._factory_versions: Dict[Tuple[ComputeBackend, str], int] = {}
        self._generation = 0
        self._lock = threading.Lock()
        self._logger = Logger.get_logger(__name__)

    def register(
        self,
        backend: ComputeBackend,
        factory: RunnerFactory,
        *,
        profile: str = DEFAULT_PROFILE,
    ) -> None:
        """Register (or override) the factory used to build the adapter for
        ``(backend, profile)``.

        Overwrites any previously cached instance for that key so a
        subsequent ``get()`` reflects the new factory immediately, rather
        than returning a stale instance built from the prior factory.
        """
        if backend == ComputeBackend.AUTO:
            raise ValueError("cannot register an adapter for 'auto'")
        key = (backend, profile)
        with self._lock:
            self._factories[key] = factory
            self._factory_versions[key] = (
                self._factory_versions.get(key, 0) + 1
            )
            self._instances.pop(key, None)

    def get(
        self, backend: ComputeBackend, *, profile: str = DEFAULT_PROFILE
    ) -> ComputeRunner:
        """Return the cached adapter instance for ``(backend, profile)``,
        constructing it on first use.

        Raises ``BackendConfigurationError`` for:
        - ``ComputeBackend.AUTO`` (must be resolved to a concrete backend
          by ``ComputeRouter``/``ComputeExecutionService`` first);
        - a backend with no registered factory and no available default
          adapter module;
        - an adapter module that cannot be imported;
        - any factory (explicitly registered or the default lazy import)
          that raises while constructing the adapter (e.g. a local
          dependency's daemon/service is unreachable);
        - an adapter class that does not (yet) implement ``ComputeRunner``.

        Every failure is raised before any provider call is possible.
        """
        if backend == ComputeBackend.AUTO:
            raise BackendConfigurationError(
                "'auto' must be resolved to a concrete backend before "
                "requesting an adapter"
            )
        key = (backend, profile)
        while True:
            with self._lock:
                cached = self._instances.get(key)
                if cached is not None:
                    return cached
                factory = self._factories.get(key) or self._default_factory(
                    backend
                )
                version = (
                    self._generation,
                    self._factory_versions.get(key, 0),
                )
            # A factory (explicitly registered, or the default lazy
            # import/construct closure below) can fail for reasons
            # outside our control — e.g. LocalRunner's __init__ eagerly
            # connects to the Docker daemon. Classify any such failure
            # the same way as an import failure, rather than letting a
            # provider-SDK exception leak out of the registry
            # unclassified. Already-classified errors pass through
            # unchanged; the original exception is preserved via
            # `from exc` otherwise.
            try:
                instance = factory()
            except Exception as exc:
                with self._lock:
                    current_version = (
                        self._generation,
                        self._factory_versions.get(key, 0),
                    )
                if current_version != version:
                    continue
                if isinstance(exc, BackendConfigurationError):
                    raise
                raise BackendConfigurationError(
                    f"backend {backend.value!r} adapter could not be "
                    f"constructed: {exc}"
                ) from exc
            if not isinstance(instance, ComputeRunner):
                with self._lock:
                    current_version = (
                        self._generation,
                        self._factory_versions.get(key, 0),
                    )
                if current_version != version:
                    continue
                raise BackendConfigurationError(
                    f"adapter for backend {backend.value!r} does not "
                    "implement the ComputeRunner contract"
                )

            with self._lock:
                cached = self._instances.get(key)
                if cached is not None:
                    return cached
                current_version = (
                    self._generation,
                    self._factory_versions.get(key, 0),
                )
                if current_version != version:
                    continue
                self._instances[key] = instance
            self._logger.info(
                "RunnerRegistry: constructed adapter backend=%s profile=%s "
                "class=%s",
                backend.value,
                profile,
                type(instance).__name__,
            )
            return instance

    def _default_factory(self, backend: ComputeBackend) -> RunnerFactory:
        module_class = _ADAPTER_MODULE_MAP.get(backend)
        if module_class is None:
            raise BackendConfigurationError(
                "no ComputeRunner adapter is registered or available for "
                f"backend {backend.value!r}"
            )
        module_name, class_name = module_class
        config = self.config

        def _factory() -> ComputeRunner:
            try:
                module = importlib.import_module(
                    f"{__package__}.{module_name}"
                )
            except ImportError as exc:
                raise BackendConfigurationError(
                    f"backend {backend.value!r} adapter module "
                    f"{module_name!r} could not be imported: {exc}"
                ) from exc
            runner_class = getattr(module, class_name, None)
            if runner_class is None:
                raise BackendConfigurationError(
                    f"backend {backend.value!r} adapter module "
                    f"{module_name!r} has no {class_name!r} class"
                )
            return runner_class(config=config)

        return _factory

    def clear(self) -> None:
        """Drop all cached instances and explicit registrations.

        Intended for test isolation between cases that register their own
        fake adapters.
        """
        with self._lock:
            self._generation += 1
            self._factories.clear()
            self._factory_versions.clear()
            self._instances.clear()
