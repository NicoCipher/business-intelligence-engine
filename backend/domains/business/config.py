"""
domains/business/config.py

Assembles the Business Intelligence DOMAIN_CONFIG from its
single-responsibility modules. This is the only file in this
domain package that imports from all sibling modules.

DOMAIN_CONFIG is the sole export consumed by DomainRegistry.
It is immutable by convention — treat it as read-only after import.
"""

from domains.base import DomainConfig
from domains.business.metadata  import METADATA
from domains.business.sources   import SOURCES
from domains.business.keywords  import KEYWORDS
from domains.business.graph     import KNOWLEDGE_GRAPH
from domains.business.scoring   import SCORING
from domains.business.reporting import REPORTING

DOMAIN_CONFIG = DomainConfig(
    metadata  = METADATA,
    sources   = SOURCES,
    keywords  = KEYWORDS,
    graph     = KNOWLEDGE_GRAPH,
    scoring   = SCORING,
    reporting = REPORTING,
)
