PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS articles (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL,
 summary TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT 'Market News',
 region TEXT NOT NULL DEFAULT 'Global',
 url TEXT NOT NULL UNIQUE,
 published_at TEXT,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','rejected')),
 filing_type TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_status_updated ON articles(status,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(status,published_at DESC);
CREATE TABLE IF NOT EXISTS economic_indicators (
 series_id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 country TEXT NOT NULL DEFAULT '',
 value TEXT NOT NULL,
 unit TEXT NOT NULL DEFAULT '',
 period TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT '',
 description TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_type TEXT NOT NULL,
 details TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL
);
INSERT INTO articles(title,summary,source,category,region,url,published_at,status,filing_type,created_at,updated_at)
VALUES('10-Q - HOME DEPOT, INC. (0000354950) (Filer)','Home Depot filed a quarterly report with the SEC on November 20, 2026. Review the original filing for the company''s financial statements, business updates, and disclosures.','SEC Form 10-Q Filings','SEC Company Filing','United States','https://www.sec.gov/Archives/edgar/data/354950/000162828026075287/0001628280-26-075287-index.htm','2026-11-20T21:21:23+00:00','published','10-Q','2026-11-20T21:21:23+00:00','2026-11-20T21:21:23+00:00')
ON CONFLICT(url) DO NOTHING;
