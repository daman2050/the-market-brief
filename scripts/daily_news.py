
"""
THE MARKET BRIEF
Global Financial News & Economic Data Collector

Purpose:
- Collect financial news from official institutional sources.
- Collect SEC company filings.
- Collect selected U.S. economic indicators.
- Deduplicate and normalize articles.
- Send collected data to the private ingestion API when configured.
- Otherwise save a local JSON output file.

Dependencies:
    pip install requests feedparser

Environment variables:
    SEC_USER_AGENT
    MARKET_BRIEF_API_URL
    MARKET_BRIEF_INGEST_SECRET
"""

import json
import logging
import os
import re
import sys
import calendar

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests


# ============================================================
# PROJECT SETTINGS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

OUTPUT_FILE = ROOT / "data" / "collector-output.json"

MAX_ARTICLES = 60
REQUEST_TIMEOUT = 25

CURRENT_YEAR = datetime.now(timezone.utc).year
START_YEAR = CURRENT_YEAR - 1

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "The Market Brief Research Contact themarketbrief@gmail.com"
)

API_URL = os.getenv("MARKET_BRIEF_API_URL", "").rstrip("/")
INGEST_SECRET = os.getenv("MARKET_BRIEF_INGEST_SECRET", "")

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": SEC_USER_AGENT,
    "Accept": "application/json, application/atom+xml, application/rss+xml, application/xml, text/xml, */*",
})


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("market_brief")


# ============================================================
# OFFICIAL NEWS SOURCES
# ============================================================

NEWS_FEEDS = [
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "Central Bank",
        "region": "United States",
    },
    {
        "name": "SEC Press Releases",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "category": "Financial Regulation",
        "region": "United States",
    },
    {
        "name": "European Central Bank",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "category": "Central Bank",
        "region": "Europe",
    },
    {
        "name": "Bank of England",
        "url": "https://www.bankofengland.co.uk/rss/news",
        "category": "Central Bank",
        "region": "United Kingdom",
    },
]


# ============================================================
# SEC FILING SOURCES
# ============================================================

SEC_FILING_TYPES = [
    "8-K",
    "10-K",
    "10-Q",
]

SEC_FEED_TEMPLATE = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent"
    "&type={filing_type}"
    "&company="
    "&dateb="
    "&owner=include"
    "&count=40"
    "&output=atom"
)


# ============================================================
# ECONOMIC INDICATORS
# ============================================================

BLS_SERIES = [
    {
        "id": "CUSR0000SA0",
        "name": "Consumer Price Index",
        "country": "United States",
        "unit": "Index",
        "description": "Consumer price index for all urban consumers.",
    },
    {
        "id": "LNS14000000",
        "name": "Unemployment Rate",
        "country": "United States",
        "unit": "%",
        "description": "Civilian unemployment rate.",
    },
    {
        "id": "CES0000000001",
        "name": "Total Nonfarm Employment",
        "country": "United States",
        "unit": "Thousands of jobs",
        "description": "Total nonfarm payroll employment.",
    },
]

BLS_API_URL = (
    "https://api.bls.gov/publicAPI/v1/timeseries/data/"
)


# ============================================================
# GENERAL UTILITIES
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean_text(value):
    """Remove HTML tags and normalize whitespace."""

    if not value:
        return ""

    value = str(value)

    value = re.sub(
        r"<script.*?</script>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    value = re.sub(
        r"<style.*?</style>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    value = re.sub(r"<[^>]+>", " ", value)

    value = re.sub(r"&nbsp;", " ", value)
    value = re.sub(r"&amp;", "&", value)
    value = re.sub(r"&quot;", '"', value)
    value = re.sub(r"&#39;", "'", value)

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def valid_http_url(value):
    """Only accept ordinary HTTP and HTTPS links."""

    if not value:
        return False

    try:
        parsed = urlparse(value)

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
        )

    except Exception:
        return False


def parse_feed_date(entry):
    """Return a normalized publication date."""

    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("created_parsed")
    )

    if parsed:
        try:
            return datetime.fromtimestamp(
                calendar.timegm(parsed),
                timezone.utc,
            ).isoformat()
        except Exception:
            pass

    return utc_now()


def truncate(value, limit=1200):
    value = clean_text(value)

    if len(value) <= limit:
        return value

    return value[:limit].rsplit(" ", 1)[0] + "..."


def normalize_article(
    title,
    summary,
    source,
    category,
    region,
    url,
    published,
    filing_type=None,
):
    """Create a consistent article record."""

    title = clean_text(title)
    summary = truncate(summary, 1200)

    if not title or not valid_http_url(url):
        return None

    article = {
        "title": title,
        "summary": summary,
        "source": source,
        "category": category,
        "region": region,
        "url": url,
        "published": published,
        "collected_at": utc_now(),
        "status": "draft",
    }

    if filing_type:
        article["filing_type"] = filing_type

    return article


# ============================================================
# NETWORK REQUESTS
# ============================================================

def get_response(url):
    """Fetch a URL with a timeout and consistent headers."""

    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response

    except requests.RequestException as error:
        logger.warning(
            "Could not retrieve %s: %s",
            url,
            error,
        )

        return None


# ============================================================
# RSS / ATOM COLLECTION
# ============================================================

def collect_feed(source):
    """Collect articles from an RSS or Atom source."""

    name = source["name"]

    logger.info("Checking %s...", name)

    response = get_response(source["url"])

    if response is None:
        return []

    try:
        parsed = feedparser.parse(response.content)

        if parsed.bozo and not parsed.entries:
            logger.warning(
                "Feed parsing failed for %s",
                name,
            )
            return []

        articles = []

        for entry in parsed.entries:
            title = entry.get("title", "")

            summary = (
                entry.get("summary")
                or entry.get("description")
                or ""
            )

            link = entry.get("link", "")

            published = parse_feed_date(entry)

            article = normalize_article(
                title=title,
                summary=summary,
                source=name,
                category=source["category"],
                region=source["region"],
                url=link,
                published=published,
            )

            if article:
                articles.append(article)

        logger.info(
            "Found %s entries from %s",
            len(articles),
            name,
        )

        return articles

    except Exception:
        logger.exception(
            "Unexpected feed error: %s",
            name,
        )

        return []


# ============================================================
# SEC COMPANY FILINGS
# ============================================================

def collect_sec_filings():
    """Collect recent SEC filing announcements."""

    all_articles = []

    for filing_type in SEC_FILING_TYPES:
        logger.info(
            "Checking SEC Form %s Filings...",
            filing_type,
        )

        url = SEC_FEED_TEMPLATE.format(
            filing_type=filing_type,
        )

        response = get_response(url)

        if response is None:
            continue

        try:
            parsed = feedparser.parse(response.content)

            if parsed.bozo and not parsed.entries:
                logger.warning(
                    "SEC feed parsing failed for %s",
                    filing_type,
                )
                continue

            articles = []

            for entry in parsed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")

                published = parse_feed_date(entry)

                summary = (
                    f"A company submitted an SEC Form "
                    f"{filing_type} filing. "
                    f"Review the original SEC filing for "
                    f"financial statements, disclosures, "
                    f"and company developments."
                )

                article = normalize_article(
                    title=title,
                    summary=summary,
                    source=f"SEC Form {filing_type} Filings",
                    category="SEC Company Filing",
                    region="United States",
                    url=link,
                    published=published,
                    filing_type=filing_type,
                )

                if article:
                    articles.append(article)

            logger.info(
                "Found %s entries from SEC Form %s",
                len(articles),
                filing_type,
            )

            all_articles.extend(articles)

        except Exception:
            logger.exception(
                "SEC filing collection failed for %s",
                filing_type,
            )

    return all_articles


# ============================================================
# BUREAU OF LABOR STATISTICS
# ============================================================

def collect_bls_data():
    """Retrieve the latest observations for selected BLS series."""

    logger.info("Checking Bureau of Labor Statistics...")

    payload = {
        "seriesid": [
            item["id"] for item in BLS_SERIES
        ],
        "startyear": str(START_YEAR),
        "endyear": str(CURRENT_YEAR),
    }

    try:
        response = SESSION.post(
            BLS_API_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        if result.get("status") != "REQUEST_SUCCEEDED":
            logger.warning(
                "BLS returned status: %s",
                result.get("status"),
            )
            return []

        returned_series = result.get("Results", {}).get(
            "series",
            [],
        )

        series_lookup = {
            item["seriesID"]: item
            for item in returned_series
        }

        economic_data = []

        for definition in BLS_SERIES:
            series_id = definition["id"]

            series = series_lookup.get(series_id)

            if not series:
                logger.warning(
                    "BLS series unavailable: %s",
                    series_id,
                )
                continue

            observations = series.get("data", [])

            if not observations:
                logger.warning(
                    "No BLS observations for %s",
                    series_id,
                )
                continue

            latest = observations[0]

            period = (
                f"{latest.get('periodName', '')} "
                f"{latest.get('year', '')}"
            ).strip()

            value = latest.get("value")

            if value is None:
                continue

            economic_data.append({
                "name": definition["name"],
                "country": definition["country"],
                "value": value,
                "unit": definition["unit"],
                "period": period,
                "source": "U.S. Bureau of Labor Statistics",
                "series_id": series_id,
                "description": definition["description"],
                "updated_at": utc_now(),
            })

            logger.info(
                "Retrieved BLS indicator: %s = %s",
                definition["name"],
                value,
            )

        logger.info(
            "Successfully collected %s BLS indicators",
            len(economic_data),
        )

        return economic_data

    except requests.RequestException as error:
        logger.warning(
            "Could not retrieve BLS data: %s",
            error,
        )

    except Exception:
        logger.exception(
            "Unexpected BLS collection error"
        )

    return []


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_articles(articles):
    """Remove duplicate stories based on URL and title."""

    unique = []
    seen_urls = set()
    seen_titles = set()

    for article in articles:
        url = article.get("url", "").strip()
        title = article.get("title", "").strip().lower()

        if not url or not title:
            continue

        if url in seen_urls or title in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title)

        unique.append(article)

    return unique


# ============================================================
# SORTING
# ============================================================

def sort_articles(articles):
    """Sort newest articles first."""

    def sort_key(article):
        value = article.get("published", "")

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).timestamp()

        except Exception:
            return 0

    return sorted(
        articles,
        key=sort_key,
        reverse=True,
    )


# ============================================================
# LOCAL OUTPUT
# ============================================================

def save_output(payload):
    """
    Save collector output locally.

    This file is intentionally named collector-output.json.
    It should not be placed in the public website directory:
    articles remain drafts until reviewed and approved.
    """

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = OUTPUT_FILE.with_suffix(".tmp")

    with temporary_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            indent=2,
            ensure_ascii=False,
        )

    temporary_file.replace(OUTPUT_FILE)

    logger.info(
        "Saved collector output to %s",
        OUTPUT_FILE,
    )


# ============================================================
# PRIVATE API INGESTION
# ============================================================

def send_to_api(payload):
    """
    Send data to the private Cloudflare Worker ingestion endpoint.

    Both environment variables must be configured.
    No secret is written into the JSON output.
    """

    if not API_URL and not INGEST_SECRET:
        logger.info(
            "API ingestion not configured. "
            "Keeping output in the local collector file."
        )
        return False

    if not API_URL or not INGEST_SECRET:
        logger.error(
            "API ingestion requires both "
            "MARKET_BRIEF_API_URL and "
            "MARKET_BRIEF_INGEST_SECRET."
        )
        return False

    endpoint = f"{API_URL}/api/ingest"

    headers = {
        "Authorization": f"Bearer {INGEST_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = SESSION.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError("The private API did not confirm ingestion.")

        logger.info(
            "Successfully sent collector data to the private API."
        )

        return True

    except requests.RequestException as error:
        logger.error(
            "Private API ingestion failed: %s",
            error,
        )

        return False


# ============================================================
# MAIN COLLECTION PROCESS
# ============================================================

def main():
    print()
    print("=" * 58)
    print("THE MARKET BRIEF - GLOBAL NEWS COLLECTOR")
    print("=" * 58)
    print()

    started_at = utc_now()

    all_articles = []

    # --------------------------------------------------------
    # 1. Official news feeds
    # --------------------------------------------------------

    print("COLLECTING GLOBAL FINANCIAL NEWS")
    print("-" * 58)

    for source in NEWS_FEEDS:
        articles = collect_feed(source)
        all_articles.extend(articles)

    # --------------------------------------------------------
    # 2. SEC company filings
    # --------------------------------------------------------

    print()
    print("COLLECTING COMPANY FILINGS")
    print("-" * 58)

    sec_articles = collect_sec_filings()
    all_articles.extend(sec_articles)

    # --------------------------------------------------------
    # 3. Deduplicate and sort
    # --------------------------------------------------------

    all_articles = deduplicate_articles(
        all_articles
    )

    all_articles = sort_articles(
        all_articles
    )

    all_articles = all_articles[:MAX_ARTICLES]

    # --------------------------------------------------------
    # 4. Economic indicators
    # --------------------------------------------------------

    print()
    print("COLLECTING ECONOMIC INDICATORS")
    print("-" * 58)

    economic_data = collect_bls_data()

    # --------------------------------------------------------
    # 5. Prepare final payload
    # --------------------------------------------------------

    payload = {
        "publication": "The Market Brief",
        "schema_version": 2,
        "collected_at": utc_now(),
        "collection_started_at": started_at,
        "article_count": len(all_articles),
        "economic_indicator_count": len(economic_data),
        "articles": all_articles,
        "economic_data": economic_data,
        "market_data": {
            "status": "not_configured",
            "message": (
                "No market-price provider has been configured "
                "with verified public-display permissions."
            ),
            "quotes": [],
            "updated_at": None,
        },
    }

    # --------------------------------------------------------
    # 6. Save local output
    # --------------------------------------------------------

    save_output(payload)

    # --------------------------------------------------------
    # 7. Optional private ingestion
    # --------------------------------------------------------

    api_success = send_to_api(payload)

    # --------------------------------------------------------
    # 8. Summary
    # --------------------------------------------------------

    print()
    print("=" * 58)
    print("COLLECTION COMPLETE")
    print("=" * 58)

    print(f"Articles collected: {len(all_articles)}")
    print(f"Economic indicators: {len(economic_data)}")
    print(f"Market price quotes: 0")
    print(f"Private API ingestion: {'SUCCESS' if api_success else 'NOT SENT'}")
    print(f"Output: {OUTPUT_FILE}")
    print()
    print(
        "Articles remain drafts until editorial approval."
    )
    print("=" * 58)
    print()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        logger.warning(
            "Collection stopped by user."
        )
        sys.exit(1)

    except Exception:
        logger.exception(
            "The collection process failed."
        )
        sys.exit(1)
