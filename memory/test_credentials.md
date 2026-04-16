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
- POST /api/admin/paywall-bypass {"email": "X"} — SAFE temp bypass (10 credits, tier=paywall_bypass, excluded from referrals/analytics)
- GET /api/admin/all-users
- POST /api/admin/create-promo {"code": "X", "tier": "walk-in", "credits": 125, "duration_days": 30, "allowed_emails": []}
- GET /api/admin/referral-analytics

## iOS Build
- **Bundle ID**: app.emergent.tattoostencils115373ef8
- **ASC App ID**: 6741930631
- **EAS Project ID**: 6f1631f5-e00d-41d1-b926-deeeb057b429

## Referral System
- **Demo user code**: BB-257527
- **Cron Secret**: X-Cron-Secret: bb-cron-2026-refresh-c7f3a1
- **Manual cron**: POST /api/referral/check-verifications (with cron header)
- **Auto cron**: Built-in, runs daily + 60s after each server restart
- **Referral landing**: GET /api/ref/{code} (no auth)
- **Dashboard**: GET /api/referral/dashboard (auth required)
- **Analytics**: GET /api/admin/referral-analytics (no auth)

## Temporary Bypass
- **Env var**: `TEMP_BYPASS_ENABLED=true` in backend/.env
- **Effect**: New signups get `tier=paywall_bypass` + 10 credits (bypasses paywall, excluded from referrals/analytics/refresh)
- **Turn off**: Set `TEMP_BYPASS_ENABLED=false` or remove the line, then redeploy
- **BBSORRY**: Walk-In tier, 125 credits, 30 days, locked to 20 affected emails
