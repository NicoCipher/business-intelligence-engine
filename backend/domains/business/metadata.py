"""
domains/business/metadata.py

Identity and UI metadata for the Business Intelligence domain.
Imported by domains/business/config.py to assemble DOMAIN_CONFIG.
"""

from domains.base import DomainMetadata

METADATA = DomainMetadata(
    id          = "business",
    name        = "Business Intelligence",
    description = (
        "Discovers market opportunities, emerging trends, and unmet demand "
        "across business, technology, and professional services."
    ),
    version     = "1.0.0",
    icon        = "briefcase",     # Tabler Icons name
    color       = "#534AB7",       # primary purple used throughout the existing UI
    category    = "business",
)
