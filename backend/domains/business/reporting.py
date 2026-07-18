"""
domains/business/reporting.py

Report template for the Business Intelligence domain.

Defines the sections the report generator renders for this domain.
The rendering engine is shared across all domains; only the template
configuration differs.

Section ids are the contract between this template and the generator.
The generator calls a render function for each id in order. Unknown
ids are skipped gracefully so new sections can be added without
breaking existing generator code.
"""

from domains.base import DomainReporting, ReportSection

REPORTING = DomainReporting(
    title="Business Intelligence Report",
    description=(
        "Weekly analysis of market opportunities, emerging trends, "
        "and unmet demand across business, technology, and professional services."
    ),
    sections=[
        ReportSection(id="executive_summary",   title="Executive Summary",    order=1),
        ReportSection(id="top_opportunities",   title="Top Opportunities",    order=2),
        ReportSection(id="signal_insights",     title="Signal Insights",      order=3),
        ReportSection(id="entity_intelligence", title="Entity Intelligence",  order=4),
        ReportSection(id="evidence",            title="Supporting Evidence",  order=5),
        ReportSection(id="recommendations",     title="Recommendations",      order=6),
    ],
)
