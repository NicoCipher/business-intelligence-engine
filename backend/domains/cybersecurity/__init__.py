"""
domains/cybersecurity — Cybersecurity Intelligence domain module (planned)

This domain is not yet implemented. When ready, it will export
DOMAIN_CONFIG covering CVEs, threat actors, advisories, and exploits.

The absence of DOMAIN_CONFIG is intentional: DomainRegistry.discover_and_register()
checks for the constant and logs a clear error if it is missing, so
listing "cybersecurity" in ACTIVE_DOMAINS produces a visible warning
rather than a silent failure.
"""
# DOMAIN_CONFIG will be exported here once the domain is implemented.
