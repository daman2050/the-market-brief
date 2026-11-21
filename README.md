# The Market Brief

Global stock-market intelligence with public market widgets, official economic indicators, a reviewed news briefing, and a private editorial desk.

## Architecture
- Public website: static assets in \`public/\`, served by Cloudflare Workers.
- Market prices: TradingView embedded widgets. Prices are supplied directly by TradingView; they are not scraped or stored by this project. Coverage and delays vary by instrument and exchange.
- News collection: \`scripts/daily_news.py\` collects institutional feeds and SEC filing announcements.
- Private ingestion: GitHub Actions sends collected material to \`POST /api/ingest\` with a bearer secret.
- Editorial database: Cloudflare D1 stores draft, published, and rejected articles plus economic indicators.
- Public APIs: only approved articles and economic indicators are exposed.
- Editorial desk: \`/admin/\`, protected by a password and signed HTTP-only session cookie.

## Cloudflare setup
The D1 database configured here is \`market-brief-db\` with ID \`8750870d-d5cb-4c58-b2e9-bfb68783ce8e\`.

1. Install Node.js LTS, then install and authenticate Wrangler:
   \`\`\`powershell
   npm install -g wrangler
   npx wrangler login
   \`\`\`
2. From the repository root, apply the D1 migration:
   \`\`\`powershell
   npx wrangler d1 migrations apply market-brief-db --remote
   \`\`\`
3. Set three Worker secrets (use separate, strong random values; do not commit them):
   \`\`\`powershell
   npx wrangler secret put ADMIN_PASSWORD
   npx wrangler secret put INGEST_SECRET
   npx wrangler secret put SESSION_SECRET
   \`\`\`
4. Deploy:
   \`\`\`powershell
   npx wrangler deploy
   \`\`\`
5. Test \`https://YOUR-WORKER-DOMAIN/api/health\`, \`/api/public/briefing\`, and \`/api/public/economic\`.
6. Open \`https://YOUR-WORKER-DOMAIN/admin/\` and sign in.

## GitHub Actions setup
In repository Settings → Secrets and variables → Actions, add:

Repository variables:
- \`MARKET_BRIEF_API_URL\`: Worker origin, e.g. \`https://the-market-brief.YOUR-SUBDOMAIN.workers.dev\` (no trailing slash).
- \`SEC_USER_AGENT\`: descriptive user agent with a monitored contact email.

Repository secret:
- \`MARKET_BRIEF_INGEST_SECRET\`: exactly the Worker \`INGEST_SECRET\` value.

The weekday collector sends drafts and economic data to the private Worker API. It no longer commits collector output or draft stories to the public repository.

## Optional automatic deployment
The \`.github/workflows/deploy-worker.yml\` workflow deploys when Worker files change on \`main\`. Add:
- Secret \`CLOUDFLARE_API_TOKEN\` with Workers Scripts edit and D1 edit permissions.
- Variable \`CLOUDFLARE_ACCOUNT_ID\`.

Until these are configured, deploy manually using Wrangler.

## Editorial workflow
1. The collector submits source material as drafts.
2. Sign in at \`/admin/\`.
3. Open the original source and verify facts, dates, and relevance.
4. Edit the headline and write an original, accurate summary with context.
5. Approve only after review. Rejected stories stay off the public site.
6. The public briefing API returns only rows with status \`published\`.

A filing announcement is not itself an explanation of a company's financial position. Do not publish generic filler as analysis.

## Security and data notes
- Drafts live in D1, outside the public static asset directory.
- Collector output is git-ignored.
- Admin changes require a valid signed session and same-origin request.
- Session cookies are Secure, HttpOnly, SameSite=Strict, and expire after eight hours.
- Keep secrets out of source control.
- This is a single-admin starter implementation; review access controls and operational needs before adding editors.

## Free-tier expectations
This avoids paid market-data APIs and uses TradingView embeds. Cloudflare and GitHub remain subject to their current free-tier quotas and terms. Third-party widget availability, data delays, and branding are controlled by TradingView.

## Financial disclosure
The Market Brief provides general educational information, not personalized investment advice or recommendations. Market data may be delayed. Readers should consult original sources and independently verify information.
