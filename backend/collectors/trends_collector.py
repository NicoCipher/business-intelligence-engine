"""
collectors/trends_collector.py — Google Trends signal collection

Data source: Google Trends, via pytrends (unofficial, reverse-engineered
  client — https://github.com/GeneralMills/pytrends)
  No authentication, no official API, no documented rate limit. This is
  qualitatively different from every other collector in this system:
  Reddit, GitHub, and Hacker News all have official APIs with documented
  limits. Google can change the underlying behavior without notice —
  this has broken pytrends before and will again. Treat this collector
  as the least reliable source in the system, not a peer of the others.

Setup: pip install pytrends. No credentials needed.

Why Google Trends?
  Reddit/HN/GitHub all surface demand through what people *write*.
  Trends surfaces demand through what people *search* — a different,
  complementary evidence type. Specifically: for each tracked keyword,
  "rising related queries" are other searches whose volume is currently
  surging alongside it. That's closer to emerging, specific,
  currently-unserved demand than anything in this text-based, so it's
  treated as a demand signal unconditionally, not via marker-matching
  against text the way Reddit/HN/GitHub tag their content.

What we collect:
  - For each configured keyword: currently-rising related queries
    (interest_over_time() decides whether to tag the parent keyword's
    signals trending_up; related_queries()['rising'] is what actually
    becomes signals — see class docstring).

Why one keyword per query, not batched:
  pytrends supports up to 5 keywords per build_payload() call, but that
  triggers Google's "compare" mode, which normalises interest values
  *relative to the group being compared* — batching would silently
  change the numbers compared to querying the same keyword alone. Since
  we want each keyword's own independent trend, not a cross-keyword
  comparison, every keyword is queried individually despite the extra
  request cost.

Why re-observing the same rising query on a later date is not a
duplicate:
  source_id is date-scoped ({keyword}|{query}|{date}). A rising query
  surging again tomorrow is a new, true observation reinforcing the
  same demand pattern, not a stale repeat — see
  docs/architecture/02_INTELLIGENCE_PRINCIPLES.md ("Recurrence
  strengthens intelligence... repeated observations of the same Problem
  increase confidence").

Tags we emit:
  - demand_signal   — unconditional, on every rising-query signal
  - breakout         — Google's own ">5000% increase" classification
  - trending_up      — the parent keyword's own search interest is
                        currently rising, not just this specific query
  - keyword:{term}   — provenance, same convention as reddit's r/{sub}
                        and github's repo:{name}
"""

import time
from datetime import date
from typing import Generator

try:
    from pytrends.request import TrendReq
    from pytrends.exceptions import TooManyRequestsError, ResponseError
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False

from .base import BaseCollector, CollectorError, ConfigurationError, RateLimitError
from config import GOOGLE_TRENDS_KEYWORD_LIMIT, GOOGLE_TRENDS_REQUEST_DELAY
from models import Signal

_TIMEFRAME = "today 3-m"       # 3-month window: recent enough for "rising", stable enough not to be noisy
_BREAKOUT_SENTINEL = 5000      # Google's own definitional floor for "Breakout" (>5000% increase)
_TREND_UP_THRESHOLD = 1.10     # later-period mean must exceed earlier-period mean by >10% to tag trending_up


class TrendsCollector(BaseCollector):
    """
    Collects rising-related-query signals from Google Trends for
    configured keywords.

    Unlike every other collector in this system, there is no
    authentication step to fail on — the only graceful-failure path is
    "pytrends is not installed."
    """

    SOURCE_NAME = "trends"
    DEFAULT_LIMIT = GOOGLE_TRENDS_KEYWORD_LIMIT

    def __init__(
        self,
        keywords: list[str] | None = None,
        domain: str = "business",
    ):
        """
        Args:
            keywords: Search terms to track. Defaults to [] (no keywords
                      -> _fetch() logs and returns, same pattern as
                      RedditCollector with no subreddits configured). In
                      the real pipeline, this comes from
                      DomainConfig.sources.trends_keywords -- see
                      pipeline.py.
            domain:   The domain these collected signals belong to.
        """
        super().__init__(domain=domain)
        self._keywords = keywords or []
        self._client: "TrendReq | None" = None

    def _get_client(self) -> "TrendReq":
        """Lazy-initialise the pytrends client. Raises CollectorError if
        the library is not installed."""
        if self._client is not None:
            return self._client

        if not PYTRENDS_AVAILABLE:
            raise ConfigurationError(
                "pytrends is not installed. Run: pip install pytrends"
            )

        self._client = TrendReq(hl="en-US", tz=360)
        return self._client

    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        if not self._keywords:
            self.logger.info("No Trends keywords configured for this domain — skipping")
            return

        client = self._get_client()
        per_keyword = max(1, limit // len(self._keywords))
        today = date.today().isoformat()
        attempted = 0
        failed    = 0

        for keyword in self._keywords:
            attempted += 1
            self.logger.debug(f"Fetching Trends for '{keyword}' (limit={per_keyword})")
            try:
                yield from self._fetch_keyword(client, keyword, per_keyword, today)
                time.sleep(GOOGLE_TRENDS_REQUEST_DELAY)
            except RateLimitError:
                raise   # propagate up to collect() for backoff
            except Exception as e:
                # One keyword failing must not stop the others
                failed += 1
                self.logger.warning(f"Failed to fetch Trends for '{keyword}': {e}")

        # A single bad keyword must never fail the whole collector — but if
        # every keyword we attempted this run failed, that is a real outage,
        # not a quiet day, and the scheduler needs to see it (backoff,
        # consecutive_failures) rather than record a false SUCCESS.
        if attempted and failed == attempted:
            raise CollectorError(
                f"All {attempted} Trends keyword(s) failed this run — "
                f"see prior per-keyword warnings for detail"
            )

    def _fetch_keyword(
        self, client: "TrendReq", keyword: str, limit: int, today: str,
    ) -> Generator[Signal, None, None]:
        try:
            client.build_payload([keyword], timeframe=_TIMEFRAME)
        except TooManyRequestsError as e:
            raise RateLimitError(f"Google Trends rate limit: {e}")
        except ResponseError as e:
            raise CollectorError(f"Google Trends request failed for '{keyword}': {e}")

        trending_up = self._is_trending_up(client, keyword)
        rising = self._get_rising_queries(client, keyword)

        for _, row in rising.head(limit).iterrows():
            signal = self._row_to_signal(keyword, row, today, trending_up)
            if signal and not self._is_duplicate(signal.source_id, domain=self.domain):
                yield signal

    def _is_trending_up(self, client: "TrendReq", keyword: str) -> bool:
        """
        Compare the mean of the later 25% of the interest-over-time
        series to the mean of the earlier 75%. A simple, documented
        heuristic -- not a claim of statistical rigor, just enough to
        distinguish "currently rising" from "flat or declining" for
        tagging purposes.
        """
        try:
            df = client.interest_over_time()
        except (TooManyRequestsError, ResponseError):
            raise
        except Exception as e:
            self.logger.debug(f"interest_over_time failed for '{keyword}': {e}")
            return False

        if df is None or df.empty or keyword not in df.columns:
            return False

        if "isPartial" in df.columns:
            df = df[df["isPartial"] == False]  # noqa: E712 -- pandas bool column

        series = df[keyword]
        if len(series) < 4:
            return False

        split = max(1, int(len(series) * 0.75))
        earlier_mean = series.iloc[:split].mean()
        later_mean = series.iloc[split:].mean()

        if earlier_mean <= 0:
            return bool(later_mean > 0)
        return bool((later_mean / earlier_mean) > _TREND_UP_THRESHOLD)

    def _get_rising_queries(self, client: "TrendReq", keyword: str):
        import pandas as pd

        try:
            result = client.related_queries()
        except (TooManyRequestsError, ResponseError):
            raise
        except Exception as e:
            self.logger.debug(f"related_queries failed for '{keyword}': {e}")
            return pd.DataFrame(columns=["query", "value"])

        rising = (result.get(keyword) or {}).get("rising")
        if rising is None:
            return pd.DataFrame(columns=["query", "value"])
        return rising

    def _row_to_signal(self, keyword: str, row, today: str, trending_up: bool) -> Signal | None:
        try:
            query = self._safe_text(str(row["query"]))
            if not query:
                return None

            raw_value = row["value"]
            is_breakout = isinstance(raw_value, str) and raw_value.strip().lower() == "breakout"
            value = _BREAKOUT_SENTINEL if is_breakout else int(raw_value)

            tags = ["demand_signal", f"keyword:{keyword}"]
            if is_breakout:
                tags.append("breakout")
            if trending_up:
                tags.append("trending_up")

            content = (
                f"Rising search query related to \"{keyword}\": search interest "
                f"in \"{query}\" has increased "
                f"{'over 5000% (Google-classified breakout)' if is_breakout else f'{value}%'} "
                f"over the {_TIMEFRAME.replace('today ', 'past ')} window."
            )

            return Signal(
                source=self.SOURCE_NAME,
                source_id=f"{keyword}|{query}|{today}",
                title=query,
                content=content,
                url=f"https://trends.google.com/trends/explore?q={query.replace(' ', '+')}",
                platform_score=value,
                comment_count=0,   # not applicable to Trends
                tags=tags,
                raw_metadata={
                    "parent_keyword": keyword,
                    "rising_value_raw": str(row["value"]),
                    "is_breakout": is_breakout,
                    "trending_up": trending_up,
                    "collected_date": today,
                    "item_type": "rising_related_query",
                },
                domain=self.domain,
            )
        except Exception as e:
            self.logger.debug(f"Skipping rising query row for '{keyword}': {e}")
            return None
