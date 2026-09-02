from domains.base import DomainSources, GreenhouseBoard, RSSFeed, StackExchangeQuery

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
    github_queries=[
        "feature request saas",
        "looking for a tool",
        "no code automation",
        "freelance workflow",
        "small business tool",
    ],
    trends_keywords=[
        "invoicing software",
        "freelance tools",
        "no code platform",
        "side hustle ideas",
        "small business automation",
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
    # Stack Exchange API queries — each entry is an independent topic.
    # tagged= is an AND query, so each StackExchangeQuery uses a single tag
    # for broad coverage.  Multi-tag entries are only for deliberate
    # intersections (e.g. wanting questions about Stripe AND subscriptions).
    #
    # Tags validated against the live SE API:
    #   stackoverflow: saas, multi-tenant, stripe-payments, webhooks,
    #                  api-design, rate-limiting, oauth-2.0
    #   freelancing:   invoicing, contracts, payment-terms
    # Tags excluded (wrong site, off-topic, or too noisy):
    #   automation (28k questions, dominated by Selenium/CI/Excel — too broad)
    #   subscription (ambiguous: RxJS/pubsub/Azure, not SaaS billing)
    #   pricing (off-topic on SO; ~450 questions, closed on arrival)
    #   startups site (shut down by Stack Exchange)
    stackexchange_queries=[
        # Stack Overflow — SaaS and API-infrastructure pain points
        StackExchangeQuery("stackoverflow", ["saas"]),
        StackExchangeQuery("stackoverflow", ["multi-tenant"]),
        StackExchangeQuery("stackoverflow", ["stripe-payments"]),
        StackExchangeQuery("stackoverflow", ["webhooks"]),
        StackExchangeQuery("stackoverflow", ["api-design"]),
        StackExchangeQuery("stackoverflow", ["rate-limiting"]),
        StackExchangeQuery("stackoverflow", ["oauth-2.0"]),
        # Freelancing Stack Exchange — solopreneur operational pain points
        StackExchangeQuery("freelancing", ["invoicing"]),
        StackExchangeQuery("freelancing", ["contracts"]),
        StackExchangeQuery("freelancing", ["payment-terms"]),
    ],
    # Greenhouse Public Job Boards — verified live against boards-api.greenhouse.io
    # Focused on SaaS, dev tools, cloud infrastructure, fintech, observability, and AI.
    greenhouse_boards=[
        GreenhouseBoard(company="Stripe", board_token="stripe"),
        GreenhouseBoard(company="Figma", board_token="figma"),
        GreenhouseBoard(company="GitLab", board_token="gitlab"),
        GreenhouseBoard(company="Vercel", board_token="vercel"),
        GreenhouseBoard(company="Datadog", board_token="datadog"),
        GreenhouseBoard(company="Cloudflare", board_token="cloudflare"),
        GreenhouseBoard(company="Grafana Labs", board_token="grafanalabs"),
        GreenhouseBoard(company="Anthropic", board_token="anthropic"),
        GreenhouseBoard(company="Scale AI", board_token="scaleai"),
        GreenhouseBoard(company="Airtable", board_token="airtable"),
        GreenhouseBoard(company="Gusto", board_token="gusto"),
        GreenhouseBoard(company="Postman", board_token="postman"),
    ],
)

