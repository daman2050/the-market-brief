
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser

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


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def get_date(entry):
    value = entry.get("published") or entry.get("updated")

    if value:
        try:
            return parsedate_to_datetime(value).astimezone(
                timezone.utc
            ).isoformat()
        except (TypeError, ValueError):
            pass

    return datetime.now(timezone.utc).isoformat()


def collect_news():
    articles = []
    seen_links = set()

    for source in FEEDS:
        print(f"Checking {source['name']}...")

        feed = feedparser.parse(source["url"])

        if feed.bozo:
            print(f"Warning: Could not fully read {source['name']}")

        for entry in feed.entries:
            title = clean_text(entry.get("title"))
            link = entry.get("link", "").strip()

            if not title or not link or link in seen_links:
                continue

            seen_links.add(link)

            articles.append({
                "title": title,
                "summary": clean_text(
                    entry.get("summary", "")
                ),
                "source": source["name"],
                "url": link,
                "published": get_date(entry),
                "status": "draft"
            })

    articles.sort(
        key=lambda article: article["published"],
        reverse=True
    )

    return articles[:MAX_ARTICLES]


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    articles = collect_news()

    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "articles": articles
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)

    print(f"Saved {len(articles)} articles to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

