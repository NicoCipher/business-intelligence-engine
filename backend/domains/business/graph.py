"""
domains/business/graph.py

Knowledge graph vocabulary for the Business Intelligence domain.
Entity types and relationships were previously defined in
knowledge_graph/schema.py as the only supported types.

They now belong here, scoped to this domain.
Cybersecurity, AI, and future domains will define their own vocabularies
without touching this file or the core engine.

Entity types: market, technology, problem, skill, regulation
Relationship types: affects, requires, enables, belongs_to, co-occurs

Imported by domains/business/config.py to assemble DOMAIN_CONFIG.
"""

from domains.base import DomainKnowledgeGraph, EntityType, RelationshipType

KNOWLEDGE_GRAPH = DomainKnowledgeGraph(
    entity_types={
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
            description="An unmet need, pain point, or inefficiency.",
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
            description="A law, standard, or regulatory requirement.",
            keywords=(
                "gdpr", "eu ai act", "ai act", "ccpa", "hipaa", "sox",
                "iso 27001", "soc 2", "pci dss",
                "wcag", "ada",
                "nis2", "dma", "dsa",
            ),
        ),
    },
    relationship_types={
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
            description=(
                "A technology enables addressing a problem or delivering a skill."
            ),
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
            description=(
                "Two entities appear together frequently across signals this week."
            ),
            valid_from=(
                "problem", "technology", "skill", "market", "regulation",
            ),
            valid_to=(
                "problem", "technology", "skill", "market", "regulation",
            ),
        ),
    },
    display_names={
        # Exact values from knowledge_graph/schema.py DISPLAY_NAMES
        "ada":        "ADA",
        "ai":         "AI",
        "ai act":     "EU AI Act",
        "api":        "API",
        "apis":       "APIs",
        "aws":        "AWS",
        "b2b":        "B2B",
        "b2c":        "B2C",
        "ccpa":       "CCPA",
        "devtools":   "developer tools",
        "dma":        "DMA",
        "dsa":        "DSA",
        "edtech":     "edtech",
        "eu ai act":  "EU AI Act",
        "fintech":    "fintech",
        "gcp":        "GCP",
        "gdpr":       "GDPR",
        "gpt":        "GPT",
        "healthtech": "healthtech",
        "hipaa":      "HIPAA",
        "iso 27001":  "ISO 27001",
        "legaltech":  "legal tech",
        "llm":        "LLM",
        "llms":       "LLMs",
        "martech":    "martech",
        "n8n":        "n8n",
        "nis2":       "NIS2",
        "pci dss":    "PCI DSS",
        "proptech":   "proptech",
        "rag":        "RAG",
        "saas":       "SaaS",
        "saas market": "SaaS market",
        "seo":        "SEO",
        "smb":        "SMB",
        "soc 2":      "SOC 2",
        "sox":        "SOX",
        "ui":         "UI",
        "ux":         "UX",
        "wcag":       "WCAG",
    },
)
