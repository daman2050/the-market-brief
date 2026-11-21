# The Market Brief

Global stock-market intelligence with public market widgets, official economic indicators, a reviewed news briefing, and a private editorial desk.

## Architecture
- Public website: static assets in `public/`, served by Cloudflare Workers.
- Market prices: TradingView embedded widgets. Prices are supplied directly by TradingView; they are not scraped or stored by this project. Coverage and delays vary by instrument and exchange.
- News collection: `scripts/daily_news.py` collects institutional feeds and SEC filing announcements.
- Private ingestion: GitHub Actions sends collected material to `POST /api/ingest` with a bearer secret.
- Editorial database: Cloudflare D1 stores draft, published, and rejected articles plus economic indicators.
- Public APIs: only approved articles and economic indicators are exposed.
- Editorial desk: `/admin/`, protected by a password and signed HTTP-only session cookie.

## Cloudflare preview setup

The branch preview uses a separate D1 database so preview testing cannot change production data.

- Preview database: `market-brief-preview-db`
- Preview database ID: `a181e798-1e94-4a90-b0f9-814af03cca50`
- Production database: `market-brief-db` (ID `8750870d-d5cb-4c58-b2e9-bfb68783ce8e`)

The preview binding in `wrangler.toml` and the migration-only file `wrangler.preview-migrations.toml` both point to the preview database. The migration-only file deliberately contains no production database ID.

1. Install Node.js LTS and authenticate Wrangler:
   ```powershell
   npm install -g wrangler
   npx wrangler login
   ```
2. From the repository root, apply migrations to the preview database only:
   ```powershell
   npx wrangler d1 migrations apply PREVIEW_DB --remote --config wrangler.preview-migrations.toml
   ```
3. Confirm the migration status against that same preview database:
   ```powershell
   npx wrangler d1 migrations list PREVIEW_DB --remote --config wrangler.preview-migrations.toml
   ```
4. After the migrations succeed, update the branch preview from this branch using:
   ```powershell
   npx wrangler preview
   ```
   If GitHub Workers Builds manages the preview deployment, pushing this branch will trigger its preview build instead.
5. Test the preview's `/api/health`, `/api/public/briefing`, and `/api/public/economic` endpoints.

Do not substitute the production database name or remove the preview migration config when applying preview migrations.

## Production Cloudflare setup

The production D1 database is `market-brief-db` with ID `8750870d-d5cb-4c58-b2e9-bfb68783ce8e`. The following commands target production and should only be run when intentionally setting up or updating the production environment:

1. Apply production migrations:
   ```powershell
   npx wrangler d1 migrations apply market-brief-db --remote
   ```
2. Set three Worker secrets (use separate, strong random values; do not commit them):
   ```powershell
   npx wrangler secret put ADMIN_PASSWORD
   npx wrangler secret put INGEST_SECRET
   npx wrangler secret put SESSION_SECRET
   ```
3. Deploy production:
   ```powershell
   npx wrangler deploy
   ```
4. Test `https://YOUR-WORKER-DOMAIN/api/health`, `/api/public/briefing`, and `/api/public/economic`.
5. Open `https://YOUR-WORKER-DOMAIN/admin/` and sign in.

## GitHub Actions setup
In repository Settings → Secrets and variables → Actions, add:

Repository variables:
- `MARKET_BRIEF_API_URL`: Worker origin, e.g. `https://the-market-brief.YOUR-SUBDOMAIN.workers.dev` (no trailing slash).
- `SEC_USER_AGENT`: descriptive user agent with a monitored contact email.

Repository secret:
- `MARKET_BRIEF_INGEST_SECRET`: exactly the Worker `INGEST_SECRET` value.

The collector is scheduled five times every day at 11:00, 14:00, 17:00, 20:00, and 23:00 UTC (approximately three hours apart). GitHub Actions uses UTC; these times shift relative to U.S. local time when daylight saving time changes. The schedule becomes active after the workflow is merged into the default branch. Each run sends newly collected stories and economic observations to the private Worker API as drafts; it does not automatically publish stories. An editor must verify and approve each story before it appears publicly. The collector no longer commits collector output or draft stories to the public repository.

## Optional automatic deployment
The `.github/workflows/deploy-worker.yml` workflow deploys when Worker files change on `main`. Add:
- Secret `CLOUDFLARE_API_TOKEN` with Workers Scripts edit and D1 edit permissions.
- Variable `CLOUDFLARE_ACCOUNT_ID`.

Until these are configured, deploy manually using Wrangler.

## Editorial workflow
1. The collector submits source material as drafts.
2. Sign in at `/admin/`.
3. Open the original source and verify facts, dates, and relevance.
4. Edit the headline and write an original, accurate summary with context.
5. Approve only after review. Rejected stories stay off the public site.
6. The public briefing API returns only rows with status `published`.

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

## Monetization and commercial flexibility

The project is intentionally not tied to one payment provider or revenue model. The current release is a publishing platform, not a paid product, and it does not activate payments or advertising automatically.

Revenue paths that can be added without replacing the core site:
- **Advertising:** reserve responsive display-ad placements in the homepage layout. Add a compliant ad provider only after approval and policy review.
- **Sponsorships:** offer clearly labeled sponsored placements or newsletter sponsorships. Keep sponsorship sales separate from editorial approval.
- **Paid membership:** add a premium tier later for member-only research, archives, or briefings. Keep public market pages and public editorial APIs independent of any membership provider.
- **Newsletter sponsorships:** connect an opt-in mailing-list provider later; collect only consented email addresses and provide unsubscribe controls.
- **Affiliate partnerships:** use disclosed, relevant affiliate links. Never imply an affiliate relationship changes the editorial view.

### Monetization safeguards
- The current homepage includes a partnership inquiry contact point; it does not claim that ad inventory is already sold.
- No ad network, affiliate tracking, mailing-list service, checkout, or payment processor is currently connected.
- Do not place ad scripts inside TradingView widgets or modify their attribution. Keep the provider's embed code and source branding intact, and check current provider terms before commercial deployment.
- Clearly label advertisements, sponsored content, and affiliate links at the point where readers encounter them. Maintain a visible disclosure policy.
- Preserve editorial independence: advertisers and sponsors cannot buy favorable coverage, change ratings, or approve independent reporting.
- Keep any future subscriber entitlements in a separate access-control layer. Do not make the public quote widgets, published editorial API, or D1 data model dependent on a specific payment vendor.
- Before enabling paid services, review applicable age, business, tax, consumer-protection, privacy, email-marketing, and payment-provider requirements with a parent/guardian and qualified professional. Payment providers may require an adult account holder.

The site can therefore begin as a free publication and add suitable revenue streams later without rebuilding its core market-data and editorial systems.
