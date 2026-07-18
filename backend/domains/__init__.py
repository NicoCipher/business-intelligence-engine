"""
domains/ — Intelligence platform domain packages

Each subdirectory is a domain module. A domain module must export a
module-level constant named DOMAIN_CONFIG of type DomainConfig.

Domains are discovered and registered by DomainRegistry.discover_and_register()
during explicit application startup — never at import time.

Importing this package has no side effects.
"""
