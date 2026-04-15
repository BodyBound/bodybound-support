# BODY BOUND Stencil Generator - PRD

## Product Overview
iOS app (Expo/React Native + FastAPI backend + MongoDB) that generates tattoo stencils from photos using AI. Designed for tattoo artists.

## Core Tech Stack
- **Frontend**: React Native (Expo SDK 54), TypeScript, expo-router
- **Backend**: FastAPI (Python), MongoDB
- **AI**: Gemini gemini-3-pro-image-preview (stencil gen), gemini-2.5-flash-image (enhancement)
- **Auth**: Apple Sign-In (primary), Google OAuth via Emergent Auth (fallback)
- **Subscriptions**: RevenueCat SDK (react-native-purchases v9.10.5)
- **Storage**: MongoDB Atlas (production), local MongoDB (preview)

## Subscription Tiers
| Tier | Price | Credits/Month | Trial Credits |
|------|-------|---------------|---------------|
| Walk-In | $14.99/mo | 125 | 10 |
| Booked Out | $29.99/mo | 500 | 10 |
| The Shop | $99.00/mo | 1,500 shared | 10 |

## Key API Endpoints
- `POST /api/ai-stencil-async` — AI stencil generation
- `POST /api/subscription/sync` — Sync RevenueCat subscription
- `POST /api/webhooks/revenuecat` — RevenueCat webhook (unauthenticated currently)
- `POST /api/promo/redeem` — Redeem promo codes
- `GET /api/diagnostics` — Visual health dashboard (HTML in browser, JSON via API)
- `GET /api/admin/user-lookup?email=X` — Look up customer by email
- `POST /api/admin/fix-subscription` — Manually activate subscription
- `POST /api/admin/add-credits` — Add bonus credits
- `GET /api/admin/all-users` — List all customers
- `POST /api/admin/create-promo` — Create promo codes

## AI Key Fallback System
- Primary: User's GOOGLE_API_KEY (pay-as-you-go)
- Backup: EMERGENT_LLM_KEY (universal key)
- Auto-fallback on auth/quota failures
- Key failures logged to `api_key_alerts` collection
- Visual dashboard at `/api/diagnostics`

## RevenueCat Webhook
- URL: `https://bodybound-subs.emergent.host/api/webhooks/revenuecat`
- Auth: Currently allowing unauthenticated (RC dashboard won't save auth header)
- Smart user matching: checks `aliases` array for backend user_ids, falls back to UUID
- Unmatched webhooks stored in `unmatched_webhooks` collection

## Promo Code System
- `BBSORRY` code created, locked to 20 affected customer emails
- Walk-In tier, 125 credits, 30 days
- One-time use per person, email-restricted
- Frontend "Apply" button added to PaywallScreen (needs new iOS build)

## Critical Rules
1. **BUNDLE ID IS SACRED**: `app.emergent.tattoostencils115373ef8`
2. **NO ios/ FOLDER**: Keep Managed Workflow
3. **AI STENCILS**: gemini-3-pro-image-preview with key fallback
4. **NO .metro-cache in git**

## Known Issues
- Production GOOGLE_API_KEY expired (AIzaSyCk...) — needs update in Emergent deployment settings
- Emergent Universal Key budget near limit — needs top-up
- RevenueCat webhook auth header won't save in RC dashboard
- Admin endpoints are unauthenticated (P2 security fix)
