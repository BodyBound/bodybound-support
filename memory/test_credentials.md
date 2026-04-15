# Test Credentials

## Demo Account
- **Endpoint**: POST /api/auth/demo-login
- **No credentials needed** - returns session_token automatically
- **User ID**: demo_reviewer_account

## RevenueCat
- **SDK API Key (Live)**: appl_dVqjUPRJXPXNpLZThAjtsqApiVU
- **Webhook Auth**: Bearer bb-rc-webhook-2026-secure-x9k2m (currently not enforced)
- **Webhook URL**: https://bodybound-subs.emergent.host/api/webhooks/revenuecat

## Admin Endpoints (no auth required currently)
- GET /api/admin/user-lookup?email=X
- POST /api/admin/fix-subscription {"email": "X", "product_id": "bodybound_1499_1m_3d"}
- POST /api/admin/add-credits {"email": "X", "credits": 25}
- GET /api/admin/all-users
- POST /api/admin/create-promo {"code": "X", "tier": "walk-in", "credits": 125, "duration_days": 30, "allowed_emails": []}

## iOS Build
- **Bundle ID**: app.emergent.tattoostencils115373ef8
- **ASC App ID**: 6741930631
- **EAS Project ID**: 6f1631f5-e00d-41d1-b926-deeeb057b429

## Promo Codes
- **BBSORRY**: Walk-In tier, 125 credits, 30 days, locked to 20 affected emails
