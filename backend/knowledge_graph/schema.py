"""
knowledge_graph/schema.py — Vocabulary for the knowledge graph

This file defines what the system can know about and what relationships
it can detect. It is the single source of truth for the entity extractor.

Design principle: adding a keyword here immediately improves recognition
everywhere — in the extractor, the scorer, the report generator — without
touching any other file. The schema is the extension point.

Why curated keywords rather than ML-based NER?
  Named entity recognition models (spaCy, NLTK) add hundreds of MB of model
  weights and require installation. LLM-based extraction costs API money.
  Curated keyword sets are zero-cost, fully transparent, and precisely tuned
  for the business intelligence domain we care about. Coverage will be lower
  than ML approaches but precision will be higher — we only recognise things
  we have explicitly decided to track.

Normalisation: all keywords are stored lowercase. The extractor lowercases
input before matching, then denormalises the extracted entity name using
DISPLAY_NAMES before storage.
"""

from dataclasses import dataclass, field


# ── Display name overrides ────────────────────────────────────────────────
# Map lowercase keywords to their canonical display names.
# Anything not in this dict is title-cased automatically.

DISPLAY_NAMES: dict[str, str] = {
    "ai":           "AI",
    "llm":          "LLM",
    "llms":         "LLMs",
    "gpt":          "GPT",
    "saas":         "SaaS",
    "api":          "API",
    "apis":         "APIs",
    "smb":          "SMB",
    "b2b":          "B2B",
    "b2c":          "B2C",
    "seo":          "SEO",
    "gdpr":         "GDPR",
    "eu ai act":    "EU AI Act",
    "ai act":       "EU AI Act",
    "ccpa":         "CCPA",
    "hipaa":        "HIPAA",
    "sox":          "SOX",
    "iso 27001":    "ISO 27001",
    "soc 2":        "SOC 2",
    "pci dss":      "PCI DSS",
    "wcag":         "WCAG",
    "ada":          "ADA",
    "nis2":         "NIS2",
    "dma":          "DMA",
    "dsa":          "DSA",
    "aws":          "AWS",
    "gcp":          "GCP",
    "rag":          "RAG",
    "n8n":          "n8n",
    "ux":           "UX",
    "ui":           "UI",
    "saas market":  "SaaS market",
    "devtools":     "developer tools",
    "fintech":      "fintech",
    "healthtech":   "healthtech",
    "edtech":       "edtech",
    "legaltech":    "legal tech",
    "martech":      "martech",
    "proptech":     "proptech",
}


def display_name(keyword: str) -> str:
    """Return the canonical display name for a keyword."""
    return DISPLAY_NAMES.get(keyword.lower(), keyword.title())


# ── Entity type definitions ───────────────────────────────────────────────

@dataclass(frozen=True)
class EntityType:
    name: str
    description: str
    # Short keywords (≤ 4 chars) require whole-word matching to avoid false positives.
    # Multi-word phrases and longer keywords use substring matching.
    keywords: tuple[str, ...]


ENTITY_TYPES: dict[str, EntityType] = {

    "market": EntityType(
        name="market",
        description="An industry, sector, or customer segment.",
        keywords=(
            "smb", "small business", "small businesses",
            "enterprise", "enterprises",
            "b2b", "b2c", "startup", "startups",
            "solopreneur", "freelancer", "freelancers",
            "agency", "agencies",
            "fintech", "healthtech", "edtech", "legaltech", "legal tech",
            "proptech", "martech", "saas market",
            "developer tools", "devtools",
            "creator economy", "gig economy",
            "e-commerce", "ecommerce",
            "remote work", "non-profit",
        ),
    ),

    "technology": EntityType(
        name="technology",
        description="A software tool, framework, language, or platform.",
        keywords=(
            "ai", "llm", "llms", "gpt", "chatgpt", "claude", "gemini",
            "openai", "anthropic",
            "python", "javascript", "typescript", "rust", "golang", "java",
            "react", "vue", "next.js", "svelte",
            "fastapi", "django", "flask",
            "sqlite", "postgresql", "redis", "mongodb", "supabase",
            "aws", "gcp", "azure", "vercel", "cloudflare",
            "notion", "airtable", "slack", "github", "figma",
            "zapier", "ifttt", "make", "n8n",
            "vector database", "embeddings", "rag", "fine-tuning",
            "automation", "webhook",
            "open source",
        ),
    ),

    "problem": EntityType(
        name="problem",
        description="An unmet need, pain point, or inefficiency people pay to solve.",
        keywords=(
            "compliance", "regulation", "audit", "security", "privacy",
            "onboarding", "retention", "churn",
            "reporting", "analytics",
            "integration", "migration",
            "documentation", "knowledge management",
            "customer support", "billing", "invoicing",
            "time tracking", "project management", "collaboration",
            "content creation", "lead generation",
            "data management", "data quality",
            "workflow automation",
        ),
    ),

    "skill": EntityType(
        name="skill",
        description="A professional skill or service type in growing demand.",
        keywords=(
            "video scripting", "copywriting", "content writing", "ghostwriting",
            "prompt engineering", "ai consulting",
            "data analysis", "data science",
            "web development", "api integration", "automation setup",
            "workflow design", "notion setup", "notion consulting",
            "compliance documentation", "legal writing", "technical writing",
            "seo writing", "email marketing", "social media management",
            "product management", "ux design",
        ),
    ),

    "regulation": EntityType(
        name="regulation",
        description="A law, standard, or regulatory requirement creating compliance demand.",
        keywords=(
            "gdpr", "eu ai act", "ai act", "ccpa", "hipaa", "sox",
            "iso 27001", "soc 2", "pci dss",
            "wcag", "ada",
            "nis2", "dma", "dsa",
        ),
    ),
}


# ── Relationship type definitions ─────────────────────────────────────────

@dataclass(frozen=True)
class RelationshipType:
    name: str
    description: str
    valid_from: tuple[str, ...]
    valid_to: tuple[str, ...]


RELATIONSHIP_TYPES: dict[str, RelationshipType] = {

    "affects": RelationshipType(
        name="affects",
        description="A problem or regulation creates pressure in a market.",
        valid_from=("problem", "regulation"),
        valid_to=("market",),
    ),

    "requires": RelationshipType(
        name="requires",
        description="A market or problem creates demand for a skill.",
        valid_from=("market", "problem"),
        valid_to=("skill",),
    ),

    "enables": RelationshipType(
        name="enables",
        description="A technology enables addressing a problem or delivering a skill.",
        valid_from=("technology",),
        valid_to=("problem", "skill"),
    ),

    "belongs_to": RelationshipType(
        name="belongs_to",
        description="A skill, problem, or technology belongs to a market context.",
        valid_from=("skill", "problem", "technology"),
        valid_to=("market",),
    ),

    "co-occurs": RelationshipType(
        name="co-occurs",
        description="Two entities appear together across multiple signals this week.",
        valid_from=("problem", "technology", "skill", "market", "regulation"),
        valid_to=("problem", "technology", "skill", "market", "regulation"),
    ),
}
