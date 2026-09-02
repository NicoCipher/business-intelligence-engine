"""
collectors/sec_edgar_collector.py — SEC EDGAR 8-K material company events collector

Data source: SEC EDGAR Submissions API (https://data.sec.gov/submissions/)
  Base URL: https://data.sec.gov/submissions/CIK{cik_10_digits}.json
  Authentication & Access Policy:
    - Free public access; no API key or paid service required.
    - SEC policy mandates declaring a custom User-Agent identifying the
      requesting application and an administrative contact email:
      Format: "Sample Company Name AdminContact@<sample company domain>.com"
    - Controlled via SEC_EDGAR_USER_AGENT. If not configured, the collector
      raises ConfigurationError to fail clearly rather than fabricating identity.
  Rate limits & throttling:
    - SEC limits traffic to a maximum of 10 requests per second across all endpoints.
    - Collector uses a conservative per-company delay (SEC_EDGAR_REQUEST_DELAY).
    - HTTP 429 raises RateLimitError immediately for scheduler backoff.
    - HTTP 403 indicating rate limiting or throttling raises RateLimitError;
      other 403s raise CollectorError.
    - Transient HTTP errors (5xx, timeouts) on individual companies are logged,
      allowing other companies to succeed. If all configured companies fail,
      raises CollectorError.

Evidence & Domain Relevance:
  - Material corporate change events disclosed under SEC Form 8-K:
    executive changes, material agreements, corporate restructuring,
    cybersecurity incidents, financial events, and operational disclosures.
  - Collector responsibility: capture clean factual evidence and provenance.
  - Downstream intelligence: interpretation of meaning (e.g. distress, growth,
    leadership disruption) belongs strictly downstream. No business conclusions
    are emitted at collection time.

Signal mapping:
  - source: "sec_edgar"
  - source_id: "{accession_number}|{cik_10_digits}" (permanent, collision-proof)
  - title: "{company_name} Form {form} ({items_summary})"
  - content: Structured factual filing summary preserving CIK, filing date,
    report date, items, primary document, and description. Safe-truncated.
  - url: Official primary document URL on sec.gov Archives.
  - platform_score: 0 (filings have no upvotes/scores)
  - comment_count: 0
  - tags: strictly source-derived:
      "sec:8-k" (or "sec:8-k/a")
      "sec:cik:<cik_10_digits>"
      "company:<normalized-company>"
      "sec:ticker:<ticker>" (when configured)
      "sec:item:<item-number>" (e.g. "sec:item:2.02", "sec:item:5.02")
  - raw_metadata: complete provenance dictionary preserving CIK, accession number,
    filing date, report date, acceptance timestamp, act, file number, film number,
    items list, document names, URLs, and XBRL flags.

Fairness & Allocation:
  - Global limit is divided evenly across configured companies upfront
    (per_company_cap = max(1, limit // n_companies)).
  - When limit >= n_companies, a high-volume company cannot starve later companies.
  - When limit < n_companies, the global ceiling halts the loop once limit is reached.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import requests

from collectors.base import (
    BaseCollector,
    CollectorError,
    ConfigurationError,
    RateLimitError,
)
from config import (
    SEC_EDGAR_LIMIT,
    SEC_EDGAR_LOOKBACK_DAYS,
    SEC_EDGAR_REQUEST_DELAY,
    SEC_EDGAR_TIMEOUT_S,
    SEC_EDGAR_USER_AGENT,
)
from domains.base import SECCompany
from models import Signal

logger = logging.getLogger(__name__)

_API_BASE = "https://data.sec.gov/submissions"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
_COMPANY_NORM_RE = re.compile(r"[^a-z0-9_-]")


def _normalize_cik(cik: str | int) -> str:
    """Format CIK as 10-digit zero-padded string."""
    clean = str(cik).strip()
    return clean.zfill(10)


def _cik_to_int_str(cik: str | int) -> str:
    """Format CIK without leading zeros for SEC Archives URL paths."""
    clean = str(cik).strip().lstrip("0")
    return clean or "0"


class SECEdgarCollector(BaseCollector):
    """Domain-scoped collector for SEC EDGAR 8-K material company filings."""

    SOURCE_NAME = "sec_edgar"
    DEFAULT_LIMIT = SEC_EDGAR_LIMIT

    def __init__(
        self,
        companies: list[SECCompany] | None = None,
        domain: str = "business",
        user_agent: str | None = None,
        lookback_days: int | None = None,
    ) -> None:
        super().__init__(domain=domain)
        self._companies: list[SECCompany] = list(companies or [])
        self._user_agent: str = (
            user_agent if user_agent is not None else SEC_EDGAR_USER_AGENT
        ).strip()
        self._lookback_days: int = (
            lookback_days if lookback_days is not None else SEC_EDGAR_LOOKBACK_DAYS
        )

    def _normalize_company(self, company: str) -> str:
        """Normalize company name for safe source-derived tagging."""
        slug = company.strip().lower().replace(" ", "-")
        return _COMPANY_NORM_RE.sub("", slug)

    def _parse_items(self, raw_items: Any) -> list[str]:
        """Parse 8-K items from SEC submissions metadata into clean strings.

        SEC submissions JSON exposes items either as a comma-separated string
        (e.g. '2.02,9.01') or list of strings. Empty or missing values return [].
        """
        if not raw_items:
            return []
        if isinstance(raw_items, str):
            return [it.strip() for it in raw_items.split(",") if it.strip()]
        if isinstance(raw_items, (list, tuple)):
            return [str(it).strip() for it in raw_items if str(it).strip()]
        return []

    def _build_tags(
        self,
        company: SECCompany,
        cik_10: str,
        form: str,
        items: list[str],
    ) -> list[str]:
        """Produce strictly source-derived tags. Zero business conclusions."""
        tags = ["sec:8-k"]
        if form.upper() == "8-K/A":
            tags.append("sec:8-k/a")

        tags.append(f"sec:cik:{cik_10}")

        norm_co = self._normalize_company(company.name)
        if norm_co:
            tags.append(f"company:{norm_co}")

        if company.ticker:
            tags.append(f"sec:ticker:{company.ticker.strip().lower()}")

        for it in items:
            tags.append(f"sec:item:{it}")

        # Deduplicate while preserving order
        return list(dict.fromkeys(tags))

    def _construct_filing_urls(
        self,
        cik_int_str: str,
        accession_number: str,
        primary_document: str,
    ) -> tuple[str, str]:
        """Construct official primary document URL and filing detail index URL.

        SEC Archives directory format:
          https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_hyphens}/
        Primary document:
          https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_hyphens}/{primary_document}
        Filing index:
          https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_hyphens}/{accession_number}-index.htm
        """
        acc_no_hyphens = accession_number.replace("-", "")
        dir_url = f"{_ARCHIVES_BASE}/{cik_int_str}/{acc_no_hyphens}"
        index_url = f"{dir_url}/{accession_number}-index.htm"

        if primary_document:
            doc_url = f"{dir_url}/{primary_document}"
        else:
            doc_url = index_url

        return doc_url, index_url

    def _filing_to_signal(
        self,
        company: SECCompany,
        filing_data: dict[str, Any],
    ) -> Signal | None:
        """Map a single 8-K filing row to a canonical BIA Signal."""
        accession_number = str(filing_data.get("accessionNumber") or "").strip()
        form = str(filing_data.get("form") or "").strip().upper()
        filing_date = str(filing_data.get("filingDate") or "").strip()

        if not accession_number or form not in ("8-K", "8-K/A") or not filing_date:
            return None

        cik_10 = _normalize_cik(company.cik)
        cik_int_str = _cik_to_int_str(company.cik)
        source_id = f"{accession_number}|{cik_10}"

        report_date = str(filing_data.get("reportDate") or "").strip()
        primary_document = str(filing_data.get("primaryDocument") or "").strip()
        primary_doc_desc = str(filing_data.get("primaryDocDescription") or "").strip()
        raw_items = filing_data.get("items")
        items = self._parse_items(raw_items)

        doc_url, index_url = self._construct_filing_urls(
            cik_int_str=cik_int_str,
            accession_number=accession_number,
            primary_document=primary_document,
        )

        tags = self._build_tags(
            company=company,
            cik_10=cik_10,
            form=form,
            items=items,
        )

        items_summary = f"Item {', '.join(items)}" if items else ""
        if items_summary:
            title = f"{company.name} Form {form} ({items_summary})"
        else:
            title = f"{company.name} Form {form}"

        # Clean factual content
        content_parts = [
            f"SEC Form {form} filing for {company.name} (CIK {cik_10}).",
            f"Filing Date: {filing_date}.",
        ]
        if report_date:
            content_parts.append(f"Report Date: {report_date}.")
        if items:
            content_parts.append(f"Reported Items: {', '.join(items)}.")
        if primary_doc_desc:
            content_parts.append(f"Document Description: {primary_doc_desc}.")

        content = self._safe_text(" ".join(content_parts), max_length=4000)

        raw_metadata = {
            "company": company.name,
            "cik": cik_10,
            "ticker": company.ticker,
            "accession_number": accession_number,
            "form": form,
            "filing_date": filing_date,
            "report_date": report_date,
            "acceptance_date_time": filing_data.get("acceptanceDateTime"),
            "act": filing_data.get("act"),
            "file_number": filing_data.get("fileNumber"),
            "film_number": filing_data.get("filmNumber"),
            "items": items,
            "primary_document": primary_document,
            "primary_doc_description": primary_doc_desc,
            "size": filing_data.get("size"),
            "is_xbrl": filing_data.get("isXBRL"),
            "is_inline_xbrl": filing_data.get("isInlineXBRL"),
            "filing_url": doc_url,
            "filing_detail_url": index_url,
        }

        return Signal(
            source=self.SOURCE_NAME,
            source_id=source_id,
            title=title,
            content=content,
            url=doc_url,
            platform_score=0,
            comment_count=0,
            tags=tags,
            domain=self.domain,
            raw_metadata=raw_metadata,
        )

    def _fetch_company_submissions(
        self,
        company: SECCompany,
        session: requests.Session,
    ) -> dict[str, Any]:
        """Fetch submissions JSON for a single company from SEC EDGAR API."""
        cik_10 = _normalize_cik(company.cik)
        url = f"{_API_BASE}/CIK{cik_10}.json"
        headers = {
            "User-Agent": self._user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }

        try:
            resp = session.get(
                url,
                headers=headers,
                timeout=SEC_EDGAR_TIMEOUT_S,
            )
        except requests.Timeout as e:
            raise CollectorError(
                f"Timeout connecting to SEC EDGAR for CIK {cik_10} ({company.name}): {e}"
            ) from e
        except requests.RequestException as e:
            raise CollectorError(
                f"Network error querying SEC EDGAR for CIK {cik_10} ({company.name}): {e}"
            ) from e

        if resp.status_code == 429:
            raise RateLimitError(
                f"SEC EDGAR rate limit reached for CIK {cik_10} (HTTP 429)"
            )

        if resp.status_code == 403:
            body_lower = resp.text.lower()
            if "rate limit" in body_lower or "throttle" in body_lower or "retry-after" in resp.headers:
                raise RateLimitError(
                    f"SEC EDGAR rate limit/throttle reached for CIK {cik_10} (HTTP 403): {resp.text[:200]}"
                )
            raise CollectorError(
                f"SEC EDGAR access forbidden for CIK {cik_10} (HTTP 403): {resp.text[:200]}"
            )

        if resp.status_code == 404:
            raise CollectorError(
                f"SEC EDGAR CIK not found {cik_10} ({company.name}) (HTTP 404)"
            )

        if resp.status_code != 200:
            raise CollectorError(
                f"SEC EDGAR HTTP {resp.status_code} for CIK {cik_10}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as e:
            raise CollectorError(
                f"SEC EDGAR returned non-JSON response for CIK {cik_10}: {e}"
            ) from e

        if not isinstance(data, dict):
            raise CollectorError(
                f"Unexpected non-dict JSON structure from SEC EDGAR for CIK {cik_10}"
            )

        return data

    def _extract_recent_filing_records(
        self,
        submissions: dict[str, Any],
        cutoff_date_str: str,
        company: SECCompany,
    ) -> list[dict[str, Any]]:
        """Extract recent 8-K filings within lookback window from columnar JSON.

        Validates that submissions JSON conforms to the required SEC EDGAR structure:
          - submissions is a dict with 'filings' as a dict
          - filings['recent'] is a dict
          - required V1 parallel arrays ('form', 'accessionNumber', 'filingDate') are lists

        Raises CollectorError if the response structure is invalid.
        Returns an empty list (without error) if the structure is valid but contains
        no matching 8-K filings.
        """
        cik_10 = _normalize_cik(company.cik)

        if not isinstance(submissions, dict) or "filings" not in submissions:
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): missing 'filings' key"
            )

        filings = submissions.get("filings")
        if not isinstance(filings, dict):
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): 'filings' must be a dict"
            )

        recent = filings.get("recent")
        if not isinstance(recent, dict):
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): 'filings.recent' must be a dict"
            )

        forms = recent.get("form")
        accessions = recent.get("accessionNumber")
        filing_dates = recent.get("filingDate")

        if not isinstance(forms, list):
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): 'form' must be a list"
            )
        if not isinstance(accessions, list):
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): 'accessionNumber' must be a list"
            )
        if not isinstance(filing_dates, list):
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): 'filingDate' must be a list"
            )

        if not (len(forms) == len(accessions) == len(filing_dates)):
            raise CollectorError(
                f"Malformed SEC EDGAR response for CIK {cik_10} ({company.name}): "
                f"parallel required array length mismatch: form={len(forms)}, "
                f"accessionNumber={len(accessions)}, filingDate={len(filing_dates)}"
            )

        length = len(forms)
        records: list[dict[str, Any]] = []

        for i in range(length):
            form = str(forms[i] or "").strip().upper()
            if form not in ("8-K", "8-K/A"):
                continue

            fdate = str(filing_dates[i] or "").strip()
            if cutoff_date_str and fdate and fdate < cutoff_date_str:
                # Filings in 'recent' are sorted reverse-chronologically;
                # once we pass the cutoff date, earlier filings can be skipped.
                continue

            record = {k: v[i] for k, v in recent.items() if isinstance(v, list) and i < len(v)}
            records.append(record)

        return records

    def _fetch(self, limit: int) -> Iterator[Signal]:
        """Fetch 8-K signals across configured companies with fairness allocation."""
        if not self._user_agent:
            raise ConfigurationError(
                "SEC EDGAR collector requires SEC_EDGAR_USER_AGENT to be configured "
                "with an application identity and contact email "
                "(e.g. 'Sample Company Name AdminContact@<sample company domain>.com')."
            )

        if not self._companies:
            self.logger.info("[%s] No SEC companies configured; skipping", self.domain)
            return

        now = datetime.now(timezone.utc)
        cutoff_date = (now - timedelta(days=self._lookback_days)).date()
        cutoff_date_str = cutoff_date.isoformat()

        n_companies = len(self._companies)
        per_company_cap = max(1, limit // n_companies)

        session = requests.Session()
        successful_companies = 0
        failed_companies = 0
        total_yielded = 0

        for idx, company in enumerate(self._companies):
            if total_yielded >= limit:
                break

            # Conservative pacing between company requests
            if idx > 0 and SEC_EDGAR_REQUEST_DELAY > 0:
                time.sleep(SEC_EDGAR_REQUEST_DELAY)

            try:
                submissions = self._fetch_company_submissions(company, session)
                filing_records = self._extract_recent_filing_records(
                    submissions,
                    cutoff_date_str=cutoff_date_str,
                    company=company,
                )
                successful_companies += 1
            except RateLimitError:
                # Re-raise rate-limiting immediately so the scheduler applies backoff
                raise
            except Exception as e:
                failed_companies += 1
                self.logger.warning(
                    "[%s] Failed querying SEC EDGAR for %s (CIK %s): %s",
                    self.domain,
                    company.name,
                    company.cik,
                    e,
                )
                continue

            company_yielded = 0
            for filing_data in filing_records:
                if company_yielded >= per_company_cap or total_yielded >= limit:
                    break

                signal = self._filing_to_signal(company, filing_data)
                if signal is None:
                    continue

                if self._is_duplicate(signal.source_id, domain=self.domain):
                    continue

                yield signal
                company_yielded += 1
                total_yielded += 1

        # Aggregate failure handling: if every company failed, raise CollectorError
        if successful_companies == 0 and failed_companies > 0:
            raise CollectorError(
                f"All {failed_companies} configured SEC EDGAR companies failed"
            )
