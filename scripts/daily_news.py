
import json
import re
import calendar
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data" / "latest-news.json"

FEEDS = [
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
    },
    {
        "name": "Bureau of Labor Statistics",
        "url": "https://www.bls.gov/feed/bls_latest.rss",
    },
]

MAX_ARTICLES = 30

HEADERS = {
    "User-Agent": "TheMarketBrief/1.0 (news collection)"
}


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def get_date(entry):
    parsed_date = entry.get("published_parsed") or entry.get("updated_parsed")

    if parsed_date:
        try:
            timestamp = calendar.timegm(parsed_date)
            return datetime.fromtimestamp(
                timestamp, timezone.utc
            ).isoformat()
        except (TypeError, ValueError, OverflowError):
            pass

    return datetime.now(timezone.utc).isoformat()


def read_feed(source):
    print(f"Checking {source['name']}...")

    response = requests.get(
        source["url"],
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    # Decode feed content while replacing invalid characters
    feed_text = response.content.decode(
        "utf-8",
        errors="replace"
    )

    # Correct an incorrect XML encoding declaration
    feed_text = re.sub(
        r'(<\?xml[^>]*encoding=["\']).*?(["\'])',
        r'\1utf-8\2',
        feed_text,
        count=1,
        flags=re.IGNORECASE
    )

    # Remove invalid XML control characters
    feed_text = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
        "",
        feed_text
    )

    feed = feedparser.parse(feed_text)

    if feed.bozo:
        print(f"Warning: Could not fully read {source['name']}")
        print(f"Feed error: {feed.bozo_exception}")

    print(f"Found {len(feed.entries)} entries from {source['name']}")

    return feed


def collect_news():
    articles = []
    seen_links = set()
    successful_feeds = 0

    for source in FEEDS:
        try:
            feed = read_feed(source)
            successful_feeds += 1

            for entry in feed.entries:
                title = clean_text(entry.get("title"))
                link = entry.get("link", "").strip()

                if not title or not link or link in seen_links:
                    continue

                seen_links.add(link)

                summary = clean_text(
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )

                # Avoid displaying a duplicate headline as a summary
                if summary.casefold() == title.casefold():
                    summary = ""

                articles.append({
                    "title": title,
                    "summary": summary,
                    "source": source["name"],
                    "url": link,
                    "published": get_date(entry),
                    "status": "draft"
                })

        except requests.RequestException as error:
            print(f"Could not retrieve {source['name']}: {error}")

        except Exception as error:
            print(f"Unexpected error with {source['name']}: {error}")

    articles.sort(
        key=lambda article: article["published"],
        reverse=True
    )

    if successful_feeds == 0:
        raise RuntimeError(
            "All news feeds failed. Existing news data was not changed."
        )

    if not articles:
        raise RuntimeError(
            "No articles were collected. Existing news data was not changed."
        )

    return articles[:MAX_ARTICLES]


def main():
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    articles = collect_news()

    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "articles": articles
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(
        f"Successfully saved {len(articles)} articles "
        f"to {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
