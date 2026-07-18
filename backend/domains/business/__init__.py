"""
domains/business — Business Intelligence domain module

Exports DOMAIN_CONFIG for registration by DomainRegistry.

This module has no import-time side effects.
Registration happens explicitly when the application calls
DomainRegistry.discover_and_register() during startup.

To activate this domain:
    ACTIVE_DOMAINS=business          # business only
    ACTIVE_DOMAINS=business,cybersecurity  # both domains active
"""

from domains.business.config import DOMAIN_CONFIG

__all__ = ["DOMAIN_CONFIG"]
