# ProfitBot Cloud v0.5 — Owner dashboard and product research MVP

ProfitBot is an owner-operated product research and decision-support tool. It is not an autonomous purchasing or payment bot. Search-interest signals and product scores are estimates, not verified demand or realized profit.

## Current capabilities
- Arabic RTL web dashboard at `/` and `/dashboard`.
- Owner-only API routes protected by a server-side bearer token.
- Product catalog with supplier, market, price, cost, shipping and fee inputs.
- Estimated net profit, margin, weighted product score and eligibility screening.
- Country-specific Google Trends RSS signals classified as product candidates.
- Approval queue with owner approve/reject decisions.
- Audit history for product and approval events.
- Health endpoint checks database connectivity and reports database backend and persistence status.

## Important limitations
- No live PayPal, RedotPay, card-processing, supplier ordering, store publishing, fulfillment or refund integration is enabled.
- Approval decisions are records only. They do not execute the requested action.
- No verified sales/order data is connected, so realized monthly net profit is unavailable.
- Google Trends measures search interest, not sales volume or guaranteed purchase intent.
- Eligibility is only a screening result. Verify supplier identity, stock, landed cost, customs, taxes, returns, delivery times and local legal requirements before buying or listing.

## Run locally
Python 3.11+ is required.
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set OWNER_API_TOKEN to a long random secret before starting.
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/` and enter the owner token. API documentation is at `/docs`.

## Environment variables
- `OWNER_API_TOKEN`: required for owner routes; set it as a hosting secret. Never commit it.
- `DATABASE_URL`: local default is SQLite. For hosted use, configure managed PostgreSQL and set its private/internal connection URL.
- `CORS_ORIGINS`: comma-separated trusted origins only. The built-in dashboard uses same-origin requests.

## Deploy safely
1. Create a managed PostgreSQL database with backups and copy its private/internal connection URL.
2. Set `DATABASE_URL` and a strong `OWNER_API_TOKEN` in the hosting service environment.
3. Deploy and confirm `/health` returns `status=ok`, `database=postgresql`, and `storage_persistent=true`.
4. Sign in at `/` and test product creation, scoring, trend retrieval, approval decisions and audit history.
5. Keep real payments and supplier actions disabled until each provider integration is implemented, tested in sandbox mode and secured with explicit limits and confirmation.

SQLite is convenient for local development. On an ephemeral hosted filesystem, SQLite data can be lost on restart or redeploy. Do not enter real business data until durable PostgreSQL storage is configured and verified.

## Launch checklist\nSee [Arabic launch checklist](LAUNCH_CHECKLIST_AR.md) for the manual go/no-go checks before the planned trial.\n\n## Automated checks
GitHub Actions compiles Python modules, runs unit tests and checks dashboard JavaScript syntax. Passing CI does not prove the public Render route, database persistence or third-party integrations work.

## Security
- Use HTTPS only and a long random owner token.
- Never paste card data, PayPal/RedotPay passwords, provider secrets or supplier passwords into the dashboard or chat.
- Keep CORS restricted, enable database backups and rotate exposed secrets.
- Before selling, verify local laws, import/customs duties, tax obligations, payment-provider eligibility and supplier terms.
