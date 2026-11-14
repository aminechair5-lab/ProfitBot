# ProfitBot Cloud v0.4 — Cloud-ready engineering foundation

This is a development foundation, not a production deployment. It adds a cloud API,
owner authentication, persistent data models, product scoring, approval queue and audit log.
It intentionally contains no live payment, supplier purchase, auto-publishing, or trading actions.

## Architecture
- Web dashboard: Arabic RTL owner console served by the FastAPI app at `/` and `/dashboard`; includes product scoring, country trend signals, approvals and audit history. It uses the same-origin API and keeps the bearer token in page memory only.\n- Android app: owner dashboard client (the previous v0.3 Android project is retained under `android/`).
- Backend: FastAPI.
- Database: SQLite for local development; PostgreSQL via `DATABASE_URL` for cloud deployment.
- Owner access: bearer token stored only as a server environment secret.
- Deployment: Dockerfile + render.yaml starter. A free tier/provider may change or sleep; verify current terms before relying on it.
- Public URL: use the provider's free subdomain initially; custom domain not required.

## Run locally
Requirements: Python 3.11+
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set OWNER_API_TOKEN to a long random value before starting.
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs`. Set the `Authorization` header as `Bearer YOUR_OWNER_API_TOKEN`.
Health endpoint `/health` is public; all owner routes require authentication.

## Environment variables
- `OWNER_API_TOKEN`: required secret; use a long random value. Never commit it.
- `DATABASE_URL`: optional; defaults to SQLite `sqlite:///./profitbot.db`.
- `CORS_ORIGINS`: optional comma-separated origins. Keep narrow in production.

## Deploy
The `Dockerfile` and `render.yaml` are starter configuration only. Create a private service in a provider dashboard,
set `OWNER_API_TOKEN`, set a persistent disk or managed PostgreSQL, and deploy from your own repository.
Do not assume free hosting includes durable storage, always-on service, or unlimited requests.
Do not paste API secrets into Android source code or chat.

## Android
`android/` contains the v0.3 Android Studio project as the UI baseline. The next Android task is to add a
server URL + owner token connection screen using Android Keystore-backed storage, then call the API over HTTPS.
This v0.4 bundle does not yet embed a token or connect the app to a live cloud host.

## Web dashboard\nAfter starting the backend, open `http://127.0.0.1:8000/`. Sign in with the server-side `OWNER_API_TOKEN`. The dashboard supports product creation and rescoring, Google Trends RSS candidate discovery by country, approval requests and decisions, and audit history. A recorded approval is not an executed transaction.\n\n## API overview
- `GET /health` — public health check
- `GET /owner/summary` — owner dashboard summary
- `GET /products` — list product candidates
- `POST /products` — create a candidate
- `POST /products/{id}/score` — calculate weighted score
- `POST /approvals` — create a pending approval request
- `GET /approvals` — list pending/recent approvals
- `POST /approvals/{id}/decision` — record owner approve/reject decision
- `GET /audit` — read audit events

Approving a request only changes its status and writes an audit event. It does NOT perform the underlying purchase, payment, publication, or transfer.
A real action executor must be implemented later with provider-specific APIs, explicit per-action confirmation, idempotency, spending limits, and rollback/reconciliation.

## Automated checks\nGitHub Actions runs Python compilation and backend unit tests on pushes to `main` / `feature/web-dashboard-v1` and pull requests targeting `main`. These checks do not replace live deployment and end-to-end testing.\n\n## Security checklist before production
- Use HTTPS only.
- Generate a high-entropy owner token and rotate it if exposed.
- Prefer proper user login/OAuth and short-lived tokens before multi-device production use.
- Use managed PostgreSQL or persistent disk; ephemeral filesystems can lose SQLite data.
- Restrict CORS, add rate limiting, backups, monitoring and dependency updates.
- Never store PayPal/RedotPay/Binance passwords or payment card details.
- Verify local laws, destination-market rules, tax/customs, supplier terms and payment-provider eligibility.
