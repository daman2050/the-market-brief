
import json
import re
import calendar
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests


# --------------------------------------------------
# PROJECT SETTINGS
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data" / "latest-news.json"

MAX_ARTICLES = 60

# Replace this placeholder with a monitored contact email
# before running the SEC collector.
SEC_CONTACT_EMAIL = "YOUR_CONTACT_EMAIL"

HEADERS = {
    "User-Agent": (
        f"TheMarketBrief/1.0 (contact: {SEC_CONTACT_EMAIL})"
    )
}

# --------------------------------------------------
# NEWS SOURCES
# --------------------------------------------------

RSS_FEEDS = [
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "Federal Reserve",
    },
    {
        "name": "SEC Press Releases",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "category": "SEC Press Release",
    },
]

# Major company filings only.
# This avoids filling the newsletter with less relevant filings.
SEC_FILING_FEEDS = [
    {
        "name": "SEC Form 8-K Filings",
        "form": "8-K",
        "url": (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            "?action=getcurrent&type=8-K&company=&dateb="
            "&owner=include&count=40&output=atom"
        ),
    },
    {
        "name": "SEC Form 10-K Filings",
        "form": "10-K",
        "url": (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            "?action=getcurrent&type=10-K&company=&dateb="
            "&owner=include&count=40&output=atom"
        ),
    },
    {
        "name": "SEC Form 10-Q Filings",
        "form": "10-Q",
        "url": (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            "?action=getcurrent&type=10-Q&company=&dateb="
            "&owner=include&count=40&output=atom"
        ),
    },
]

# --------------------------------------------------
# BLS ECONOMIC DATA
# --------------------------------------------------

BLS_API_URL = (
    "https://api.bls.gov/publicAPI/v1/timeseries/data/"
)

BLS_SERIES = {
    "CUSR0000SA0": {
        "name": "Consumer Price Index (CPI)",
        "description": (
            "Consumer prices for all urban consumers, "
            "U.S. city average, seasonally adjusted."
        ),
        "unit": "Index",
    },
    "LNS14000000": {
        "name": "Unemployment Rate",
        "description": (
            "Civilian unemployment rate, seasonally adjusted."
        ),
        "unit": "Percent",
    },
    "CES0000000001": {
        "name": "Nonfarm Payrolls",
        "description": (
            "Total nonfarm employees, seasonally adjusted."
        ),
        "unit": "Thousands of jobs",
    },
}


# --------------------------------------------------
# GENERAL HELPERS
# --------------------------------------------------

def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def get_date(entry):
    parsed_date = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if parsed_date:
        try:
            timestamp = calendar.timegm(parsed_date)

            return datetime.fromtimestamp(
                timestamp,
                timezone.utc
            ).isoformat()

        except (
            TypeError,
            ValueError,
            OverflowError
        ):
            pass

    return datetime.now(timezone.utc).isoformat()


def download_feed(name, url):
    print(f"Checking {name}...")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if feed.bozo:
        print(
            f"Warning: Feed parsing issue for {name}: "
            f"{feed.bozo_exception}"
        )

    print(
        f"Found {len(feed.entries)} entries from {name}"
    )

    return feed


# --------------------------------------------------
# NEWS COLLECTION
# --------------------------------------------------

def collect_rss_articles():
    articles = []
    seen_links = set()
    successful_sources = 0

    all_feeds = RSS_FEEDS + [
        {
            "name": source["name"],
            "url": source["url"],
            "category": "SEC Company Filing",
            "form": source["form"],
        }
        for source in SEC_FILING_FEEDS
    ]

    for source in all_feeds:
        try:
            feed = download_feed(
                source["name"],
                source["url"]
            )

            successful_sources += 1

            for entry in feed.entries:
                title = clean_text(
                    entry.get("title")
                )

                link = entry.get("link", "").strip()

                if not title or not link:
                    continue

                if link in seen_links:
                    continue

                seen_links.add(link)

                summary = clean_text(
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )

                if summary.casefold() == title.casefold():
                    summary = ""

                article = {
                    "title": title,
                    "summary": summary,
                    "source": source["name"],
                    "category": source["category"],
                    "url": link,
                    "published": get_date(entry),
                    "status": "draft",
                }

                if "form" in source:
                    article["filing_type"] = source["form"]

                articles.append(article)

        except requests.RequestException as error:
            print(
                f"Could not retrieve {source['name']}: "
                f"{error}"
            )

        except Exception as error:
            print(
                f"Unexpected error with {source['name']}: "
                f"{error}"
            )

    articles.sort(
        key=lambda article: article["published"],
        reverse=True
    )

    return articles[:MAX_ARTICLES], successful_sources


# --------------------------------------------------
# BLS DATA COLLECTION
# --------------------------------------------------

def collect_bls_data():
    print("Checking Bureau of Labor Statistics API...")

    current_year = datetime.now(timezone.utc).year

    payload = {
        "seriesid": list(BLS_SERIES.keys()),
        "startyear": str(current_year - 2),
        "endyear": str(current_year),
    }

    response = requests.post(
        BLS_API_URL,
        headers={
            **HEADERS,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45
    )

    response.raise_for_status()

    result = response.json()

    if result.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(
            "BLS API did not report success: "
            + str(result.get("message", "Unknown error"))
        )

    economic_data = []

    returned_series = (
        result.get("Results", {})
        .get("series", [])
    )

    for series in returned_series:
        series_id = series.get("seriesID")

        if series_id not in BLS_SERIES:
            continue

        metadata = BLS_SERIES[series_id]

        observations = series.get("data", [])

        # Exclude annual totals and other non-monthly periods.
        monthly_observations = [
            item for item in observations
            if re.fullmatch(r"M(0[1-9]|1[0-2])", item.get("period", ""))
        ]

        if not monthly_observations:
            print(
                f"No monthly observations returned for "
                f"{metadata['name']}"
            )
            continue

        latest = max(
            monthly_observations,
            key=lambda item: (
                int(item["year"]),
                int(item["period"][1:])
            )
        )

        economic_data.append({
            "name": metadata["name"],
            "description": metadata["description"],
            "series_id": series_id,
            "value": latest.get("value"),
            "unit": metadata["unit"],
            "period": latest.get("periodName"),
            "year": latest.get("year"),
            "published": (
                f"{latest.get('year')}-"
                f"{latest.get('period', '')}"
            ),
            "footnotes": [
                note.get("text", "")
                for note in latest.get("footnotes", [])
                if note.get("text")
            ],
            "source": "Bureau of Labor Statistics",
            "url": "https://www.bls.gov/",
            "status": "draft",
        })

    print(
        f"Collected {len(economic_data)} BLS data series"
    )

    if not economic_data:
        raise RuntimeError(
            "BLS API returned no usable economic data."
        )

    return economic_data


# --------------------------------------------------
# SAVE RESULTS
# --------------------------------------------------

def save_data(articles, economic_data):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    data = {
        "last_updated": datetime.now(
            timezone.utc
        ).isoformat(),
        "articles": articles,
        "economic_data": economic_data,
    }

    # Write to a temporary file first so an interrupted
    # run does not leave a partially written JSON file.
    temporary_file = OUTPUT_FILE.with_suffix(".tmp")

    with open(
        temporary_file,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    temporary_file.replace(OUTPUT_FILE)

    print(
        f"Successfully saved {len(articles)} articles "
        f"and {len(economic_data)} economic data series "
        f"to {OUTPUT_FILE}"
    )


# --------------------------------------------------
# MAIN PROGRAM
# --------------------------------------------------

def main():
    print("=" * 50)
    print("THE MARKET BRIEF - DAILY NEWS COLLECTOR")
    print("=" * 50)

    articles, successful_feeds = collect_rss_articles()

    economic_data = []

    try:
        economic_data = collect_bls_data()

    except requests.RequestException as error:
        print(f"Could not retrieve BLS data: {error}")

    except Exception as error:
        print(f"BLS data collection error: {error}")

    if successful_feeds == 0 and not economic_data:
        raise RuntimeError(
            "All news sources failed. "
            "Existing news data was not changed."
        )

    if not articles and not economic_data:
        raise RuntimeError(
            "No new information was collected. "
            "Existing news data was not changed."
        )

    save_data(articles, economic_data)

    print("=" * 50)
    print("NEWS COLLECTION FINISHED")
    print("=" * 50)


if __name__ == "__main__":
    main()
