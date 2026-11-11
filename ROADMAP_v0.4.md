# v0.4 engineering roadmap

## Completed in this package
- Cloud-ready FastAPI service.
- SQLAlchemy data models for product candidates, approvals and audit events.
- Bearer-token owner guard (fail-closed if missing).
- Product score and net-profit estimate endpoint logic.
- Approval queue that records owner decisions without executing external actions.
- Docker and cloud deployment starter configuration.
- Previous Android v0.3 UI copied under `android/`.

## Not yet implemented
- Real hosting deployment or public URL.
- PostgreSQL provisioned database.
- Android-to-cloud HTTPS client and secure token storage.
- Live Reddit, Google Trends, supplier, Blogger, storefront or payment integrations.
- Background discovery scheduler.
- Real order fulfillment, payment execution, refunds or publishing.

## Recommended next sprint
1. Deploy private API and managed database, first with a private test environment.
2. Add Android connection settings; save token using Android Keystore/EncryptedSharedPreferences.
3. Add API client with HTTPS, timeouts, retry policy and clear offline state.
4. Add source provenance and `last_verified_at` for each market signal.
5. Implement scheduled discovery only after selecting permitted API sources and respecting rate limits.
6. Add per-country eligibility checks (shipping, payment acceptance, returns, taxes and consumer law) before a market/product can be activated.
