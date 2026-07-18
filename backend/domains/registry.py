"""
domains/registry.py — Domain registry

DomainRegistry is the single component responsible for:
  1. Reading which domains are active (ACTIVE_DOMAINS env var)
  2. Importing each named domain package
  3. Reading its DOMAIN_CONFIG constant
  4. Registering and validating the config

Nothing else in the codebase registers domains.
Nothing else in the codebase imports specific domain packages directly.

Lifecycle
─────────
  Application startup (main.py lifespan, collect.py main):
      DomainRegistry.discover_and_register()

  Core pipeline:
      for domain in DomainRegistry.get_active():
          run_pipeline(domain)

  Tests — two valid patterns:
      # Pattern A: register a hand-built fixture (no filesystem)
      DomainRegistry.clear()
      DomainRegistry.register(my_test_config)

      # Pattern B: import the real config constant (no registry side effect)
      from domains.business import DOMAIN_CONFIG
      assert DOMAIN_CONFIG.id == "business"

Thread safety
─────────────
Class-level dict mutation is not protected by a lock.
For V1 (single-process startup, read-only at runtime) this is acceptable.
Add threading.RLock if concurrent registration is ever required.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domains.base import DomainConfig

logger = logging.getLogger(__name__)

_ENV_VAR  = "ACTIVE_DOMAINS"
_DEFAULT  = "business"


class DomainRegistry:
    """
    Registry of active intelligence domains.

    All methods are classmethods — the registry is a global singleton
    accessible without passing an instance around.

    No domain module should reference this class directly.
    Only the core startup code (main.py, collect.py) calls
    discover_and_register(). Domain modules only export DOMAIN_CONFIG.
    """

    _registry: dict[str, "DomainConfig"] = {}

    # ── Startup ───────────────────────────────────────────────────────────

    @classmethod
    def discover_and_register(cls) -> None:
        """
        Read ACTIVE_DOMAINS, import each domain package, and register its
        DOMAIN_CONFIG. Called once explicitly during application startup.

        ACTIVE_DOMAINS format: comma-separated domain ids.
        Example: ACTIVE_DOMAINS=business,cybersecurity

        Default (env var absent or empty): "business"

        A domain id must match a subdirectory under domains/ that exports
        a module-level DOMAIN_CONFIG constant of type DomainConfig.

        Errors (missing package, missing constant, invalid config) are logged
        and skipped so that one bad domain does not prevent others from loading.
        """
        ids = cls._parse_active_ids()
        logger.info("Loading domains: %s", ids)

        for domain_id in ids:
            cls._import_and_register(domain_id)

        registered = cls.names()
        if registered:
            summary = ", ".join(
                f"'{n}' v{cls._registry[n].metadata.version}"
                for n in registered
            )
            logger.info("Domain registry ready — active domains: %s", summary)
        else:
            logger.error(
                "Domain registry is empty after startup. "
                "Check ACTIVE_DOMAINS and ensure domain packages are importable."
            )

    @classmethod
    def _import_and_register(cls, domain_id: str) -> None:
        """
        Import the domain package for `domain_id`, read its DOMAIN_CONFIG,
        and register it. All failures are logged; none are re-raised.
        """
        module_path = f"domains.{domain_id}"

        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            logger.error(
                "Cannot import domain '%s' from '%s': %s — "
                "verify that domains/%s/__init__.py exists and is importable.",
                domain_id, module_path, exc, domain_id,
            )
            return

        config = getattr(module, "DOMAIN_CONFIG", None)
        if config is None:
            logger.error(
                "Domain package '%s' does not export DOMAIN_CONFIG. "
                "Add 'from domains.%s.config import DOMAIN_CONFIG' "
                "to domains/%s/__init__.py.",
                domain_id, domain_id, domain_id,
            )
            return

        try:
            cls.register(config)
        except ValueError:
            # register() already logged the validation error
            pass

    # ── Registration ──────────────────────────────────────────────────────

    @classmethod
    def register(cls, config: "DomainConfig") -> None:
        """
        Validate and add a DomainConfig to the registry.

        Also the entry point for direct registration in tests:
            DomainRegistry.clear()
            DomainRegistry.register(my_fixture_config)

        Raises ValueError if config.validate() fails.
        Logs a warning (not an error) if a domain with the same id is
        already registered — the new config replaces the old one.
        """
        # Validate before touching the registry so a bad config
        # never leaves the registry in a partially-updated state.
        config.validate()

        if config.id in cls._registry:
            logger.warning(
                "Domain '%s' is already registered — overwriting. "
                "Expected during test runs; should not occur in production.",
                config.id,
            )

        cls._registry[config.id] = config
        logger.info(
            "Domain registered: '%s' (%s) v%s",
            config.id,
            config.metadata.name,
            config.metadata.version,
        )

    # ── Queries ───────────────────────────────────────────────────────────

    @classmethod
    def get(cls, domain_id: str) -> "DomainConfig":
        """
        Return a registered domain by id.
        Raises KeyError if not registered.
        """
        if domain_id not in cls._registry:
            available = ", ".join(f"'{n}'" for n in sorted(cls._registry)) or "(none)"
            raise KeyError(
                f"Domain '{domain_id}' is not registered. "
                f"Available: {available}. "
                f"Has DomainRegistry.discover_and_register() been called?"
            )
        return cls._registry[domain_id]

    @classmethod
    def get_active(cls) -> list["DomainConfig"]:
        """
        Return all registered (= active) domains in registration order.

        The core pipeline iterates over this list:
            for domain in DomainRegistry.get_active():
                run_collection_for(domain)
                run_scoring_for(domain)
        """
        return list(cls._registry.values())

    @classmethod
    def all(cls) -> dict[str, "DomainConfig"]:
        """Return a shallow copy of the full registry dict."""
        return dict(cls._registry)

    @classmethod
    def names(cls) -> list[str]:
        """Sorted list of all registered domain ids."""
        return sorted(cls._registry.keys())

    @classmethod
    def is_registered(cls, domain_id: str) -> bool:
        """Return True if a domain with this id is currently registered."""
        return domain_id in cls._registry

    @classmethod
    def count(cls) -> int:
        """Number of registered domains."""
        return len(cls._registry)

    # ── Test support ──────────────────────────────────────────────────────

    @classmethod
    def clear(cls) -> None:
        """
        Remove all registered domains.

        USE ONLY IN TESTS for isolation between test cases.
        Calling this in production startup will cause the pipeline to fail.
        """
        cls._registry.clear()
        logger.debug("DomainRegistry cleared (test isolation).")

    # ── Internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_active_ids() -> list[str]:
        """
        Parse ACTIVE_DOMAINS into a list of domain id strings.
        Strips whitespace. Returns ["business"] if unset or empty.
        """
        raw = os.environ.get(_ENV_VAR, "").strip()
        if not raw:
            logger.debug(
                "%s not set — defaulting to '%s'", _ENV_VAR, _DEFAULT
            )
            return [_DEFAULT]

        ids = [part.strip() for part in raw.split(",") if part.strip()]
        if not ids:
            logger.warning(
                "%s is set but produced no valid ids after parsing — "
                "defaulting to '%s'", _ENV_VAR, _DEFAULT
            )
            return [_DEFAULT]

        return ids
