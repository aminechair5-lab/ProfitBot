# ProfitBot Android Cloud Connection (v0.5)

## Cloud connection
The Android app now has an **اتصال الخادم** screen. Enter the owner token created in Render as `OWNER_API_TOKEN`. The token is held in app memory only and is not saved to disk or bundled into the APK.

The app calls:
- `GET /owner/summary`
- `GET /products`

using HTTPS and an `Authorization: Bearer <token>` header.

## Build
Open the `android/` directory in Android Studio, allow Gradle Sync, then use **Build > Build Bundle(s) / APK(s) > Build APK(s)**.

## Important
- Do not commit the owner token or any API secrets.
- The app does not execute payments, purchases, refunds, publishing, or transfers.
- Existing sample product cards are explicitly demo data. Cloud products appear in the connection screen.
- Cloud database persistence must be configured separately before relying on production data.
