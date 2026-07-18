"""
domains/business/sources.py

Data collection sources for the Business Intelligence domain.
These values were previously hardcoded in config.REDDIT_SUBREDDITS
and collectors/rss_collector.DEFAULT_RSS_FEEDS.

Imported by domains/business/config.py to assemble DOMAIN_CONFIG.
The core pipeline reads these at collection time via DomainRegistry.
"""

from domains.base import DomainSources, RSSFeed

SOURCES = DomainSources(
    reddit_sources=[
        "entrepreneur",
        "freelance",
        "sidehustle",
        "smallbusiness",
        "nocode",
        "SaaS",
        "digitalnomad",
        "juststart",
    ],
    rss_feeds=[
        RSSFeed(
            url="https://hnrss.org/ask",
            description="Ask HN — direct questions (high-value demand signal)",
        ),
        RSSFeed(
            url="https://hnrss.org/show",
            description="Show HN — product launches (market entry signal)",
        ),
        RSSFeed(
            url=(
                "https://hnrss.org/newest"
                "?q=freelance+OR+saas+OR+automation+OR+side+project"
            ),
            description="HN keyword filter — opportunity-adjacent discussions",
        ),
        RSSFeed(
            url="https://stackoverflow.com/feeds/tag/saas",
            description="Stack Overflow SaaS tag — technical demand signals",
        ),
        RSSFeed(
            url="https://stackoverflow.com/feeds/tag/automation",
            description="Stack Overflow automation tag — skill demand signals",
        ),
    ],
)
