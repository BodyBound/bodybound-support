# Test Credentials

## Demo Account
- **Endpoint**: POST /api/auth/demo-login
- **No credentials needed** - returns session_token automatically
- **User ID**: demo_reviewer_account

## RevenueCat
- **SDK API Key (Live)**: appl_dVqjUPRJXPXNpLZThAjtsqApiVU
- **Webhook Auth**: Bearer bb-rc-webhook-2026-secure-x9k2m (currently not enforced)
- **Webhook URL**: https://bodybound-subs.emergent.host/api/webhooks/revenuecat

## Admin Tool
- URL: https://bodybound-subs.emergent.host/api/admin-panel (after deploy)
- Preview: https://stencil-ai-fallback.preview.emergentagent.com/api/admin-panel
- Login: bodyboundstencil@yahoo.com / Body.Bound.Admin.72410
- Session: 12h expiry, rate-limited (5 attempts / 5 min lockout)

## Admin Endpoints (secured — require admin JWT)
- POST /api/admin-auth/login
- GET /api/admin-auth/me
- GET /api/admin-tool/dashboard
- GET /api/admin-tool/search?q=X
- GET /api/admin-tool/user/{email}
- POST /api/admin-tool/action/grant-credits
- POST /api/admin-tool/action/change-tier
- POST /api/admin-tool/action/reset-account
- POST /api/admin-tool/action/paywall-bypass
- GET /api/admin-tool/errors/webhooks
- GET /api/admin-tool/errors/generation
- GET /api/admin-tool/errors/sync
- GET /api/admin-tool/audit-log

## Legacy Admin Endpoints (no auth required currently)
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
