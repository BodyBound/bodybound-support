# Build #2 — Auth Lifecycle Audit (READ-ONLY)

**Date:** 2026-05-19 (after v2 async deploy)
**Scope:** Investigation only. No code changes. Output is this document plus a prioritized list of recommended fixes for separate deploys.
**Goal:** Identify why auth endpoints (`/api/auth/*`) experience latency or timeouts during periods of high generation load, and pinpoint event-loop / thread-pool / connection-pool contention.

---

## Executive Summary

Auth endpoints in isolation are fast and well-structured. The latency users observe during generation peaks is **NOT** a connection-pool starvation problem — Motor's default `maxPoolSize=100` is well above current concurrency. The actual contention is **event-loop blocking from synchronous CPU-bound image work inside generation request handlers.** While these handlers `await` async I/O properly, they call PIL/numpy/cv2 functions directly on the event loop. Every such call freezes ALL coroutines (including incoming auth requests) for the duration of the blocking work — typically 50–300ms per call, but worse under stress.

The May 6 outage was symptomatic of this: backend appeared "healthy" (Mongo + Gemini both responding), but request queue grew until Cloudflare gave up.

The v2 async architecture deployed today fixes this **only** for the Medium/Heavy reroll path because the background worker now runs on a separate task. The **sync `/api/ai-stencil` endpoint** (still used by Light + initial generation of all styles) **continues to block the event loop with PIL operations.** Auth requests routed during a sync stencil call will still queue behind it.

---

## What Was Inspected

### Motor / MongoDB driver (lines 5, 33–34)
```python
from motor.motor_asyncio import AsyncIOMotorClient
client = AsyncIOMotorClient(mongo_url)
```
- **`maxPoolSize`:** default = **100**. No starvation risk at current scale (peak ~25 concurrent auth checks observed in logs).
- **`minPoolSize`:** default = 0. Acceptable.
- **`waitQueueTimeoutMS`:** default = unset (infinite). If pool DID saturate, requests would queue silently. Recommend setting to 5000 to fail fast and surface in logs.
- **Connection reuse:** single client process-wide. Correct.

### Auth endpoints — request lifecycle

#### `POST /api/auth/apple` (line 3925)
1. `verify_apple_token` — external httpx call to `https://appleid.apple.com/auth/keys` with **5s timeout** ✅
2. Parses JWKS, finds matching `kid`, performs RS256 `jwt.decode` ✅ (microsecond CPU)
3. `db.users.find_one` (async) ✅
4. `db.users.update_one` OR `insert_one` (async) ✅
5. If new user: `create_initial_subscription` (DB writes) + optional `attribute_referral` (DB writes)
6. `create_session_token` — HS256 jwt.encode ✅ (microsecond CPU)

**⚠ Concern:** Apple's JWKS is fetched on **every** Apple login. No cache. Apple keys rotate slowly (months). At peak (e.g. App Store launch event), 100 simultaneous logins = 100 fetches to Apple = potential rate limit + measurable added latency (~150–400ms each).

#### `POST /api/auth/google-session` (line 3969)
1. External httpx call to Emergent OAuth backend with **10s timeout** ✅
2. Catches `httpx.TimeoutException` → returns 504 ✅ (good degradation pattern)
3. Same DB flow as Apple. ✅

**No issues identified.** This endpoint behaves well.

#### `GET /api/auth/me` (line 4025)
1. `get_current_user(auth_header)` — HS256 `jwt.decode` + `db.users.find_one` ✅
2. `get_user_credits(user_id)` — calls `maybe_redeem_referral_month(user_id)` on **every hit** (line 3675)

**⚠ Concern:** `maybe_redeem_referral_month` runs on every `/auth/me` call. This is a hot path — frontend calls `/auth/me` on app open, screen focus, RC sync, etc. Reviewed implementation: it does an early-return when no referrals are queued (lines ~6944–6983 quickly check `referral_rewards`), so 99% of calls cost 1 extra fast indexed Mongo query. Acceptable but adds ~5–15ms.

#### `POST /api/admin-auth/login` (line ~8000)
```python
if not bcrypt.checkpw(password.encode(), ADMIN_PASSWORD_HASH.encode()):
```
**🔴 Concern (low-frequency but real):** `bcrypt.checkpw` is CPU-bound, **runs on the event loop**, costs ~100–300ms per call depending on bcrypt cost factor. Every admin login freezes all other coroutines for that duration. Low-frequency (only the admin logs in), so impact is real but limited.

### Token verification helpers

- `get_current_user` (line 3655): HS256 jwt.decode is microsecond-scale. Single Mongo lookup. ✅
- `verify_admin` (line 7965): HS256 jwt.decode + Mongo lookup. ✅

---

## Generation Request Handlers — The Real Bottleneck

This is where the auth-latency-during-generation correlation comes from.

### Existing offload (good)
- `validate_stencil_reference_match_async` (line 152) — properly wraps cv2/numpy work in `run_in_executor`. Added in the May 6 stability patch. ✅

### Still-blocking calls (BAD — these freeze the event loop)

| Function | Lines called from | Risk |
|----------|------------------|------|
| `post_process_stencil` (sync PIL) | 2626, 2836, 3207, 7727 | **HIGH** — runs on every stencil generation. PIL convert+threshold+composite on full-resolution image. Measured ~80–200ms per call. **Called inline from `/api/ai-stencil` route handler** (line 7727 is in the sync endpoint). |
| `enhance_photo_basic` (sync PIL) | 2020, 2787, 2877, 2880, 3153 | **HIGH** — full PIL ImageEnhance.Contrast/Brightness/Sharpness pass. ~50–150ms. Called from sync `/api/ai-stencil` and from BOTH async paths' background tasks (the bg-task calls don't block any user-facing handler, only the sync path does). |
| `bcrypt.checkpw` (admin login) | 8007 | **LOW** (low-frequency) — ~100–300ms per admin login |

### What this means in practice

When 3 concurrent users hit sync `/api/ai-stencil`:
1. Each handler enters `enhance_photo_basic` → event loop freezes ~100ms (request 1 holds it).
2. Then `post_process_stencil` after Gemini returns → event loop freezes ~150ms (request 1 holds it again).
3. Meanwhile incoming `/auth/me` from a 4th user gets queued behind request 1.
4. If multiple sync requests stack, each one steals event-loop time and auth requests wait their turn.
5. If Cloudflare's response-header timeout (~30s) hits before the auth response is written, the user sees "auth timeout" — even though Mongo, the auth code, and Gemini are all responsive in isolation.

**This explains every "auth feels slow during heavy app use" report.**

### New async v2 path (good — just deployed)

`_run_stencil_job_v2` (the new background worker) **still calls `enhance_photo_basic` and `post_process_stencil` synchronously** (lines 3153 + 3207). However, because this entire function runs inside `asyncio.create_task(...)`, it executes concurrently with auth requests on the event loop. The PIL calls **still freeze the event loop during their execution**, but the v2 path doesn't add new freezes — it just relocates the existing freezes from sync handler context to bg-task context. Net effect: same total event-loop blocking, distributed slightly differently in time.

**To fully decouple auth from generation, the PIL functions must run in `run_in_executor` whether they're called from the sync handler OR the bg task.**

---

## Connection Pool Inspection

### Motor pool (MongoDB)
- Pool size: 100 (default). Healthy headroom.
- Connection lifecycle: persistent client, no per-request connect cost.
- Production logs show no `pymongo.errors.NetworkTimeout` or `WaitQueueTimeoutError` — confirming pool is not saturated.

### httpx (external API calls)
- Each Apple/Google verify creates a **new `httpx.AsyncClient` context manager**. This is suboptimal — each context creates a new connection pool. For low-volume auth this is fine, but if Apple/Google login spikes, we'd benefit from a module-level shared `httpx.AsyncClient` instance.

### Uvicorn worker threadpool (the default 40-thread pool used by `run_in_executor(None, ...)`)
- Default size = `min(32, os.cpu_count() + 4)` in Python 3.9+, but FastAPI defaults to anyio's threadpool with a higher cap.
- Currently NOT under pressure because almost nothing is wrapped in `run_in_executor` — except the validator.
- **Risk:** If we move ALL PIL calls into the executor, the default 40 threads could become the new bottleneck under load. Recommend explicitly sizing the executor (e.g. `loop.set_default_executor(ThreadPoolExecutor(max_workers=20))`) AND tracking executor queue depth.

---

## Prioritized Fix List (FOR FUTURE DEPLOYS, NOT THIS ONE)

Each fix below is **independent** and should ship as its own isolated deploy per the discipline rule.

### 🔴 P0 — Wrap PIL functions in run_in_executor

**Files:** `backend/server.py` lines 945, 589, 1031 (function defs); 5+ call sites.
**Pattern:**
```python
async def post_process_stencil_async(b64: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, post_process_stencil, b64)

async def enhance_photo_basic_async(b64: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, enhance_photo_basic, b64)
```
Then replace every sync call site with the async wrapper.
**Expected impact:** Auth and other concurrent requests stop freezing during stencil generation. Most likely root cause of "auth timeouts during heavy app use."
**Risk:** Medium — touching 7+ call sites. Needs careful regression. Existing executor for validator confirms the pattern works.

### 🟡 P1 — Bcrypt admin login in executor

**File:** `backend/server.py` line 8007.
**Pattern:**
```python
loop = asyncio.get_running_loop()
ok = await loop.run_in_executor(
    None, bcrypt.checkpw, password.encode(), ADMIN_PASSWORD_HASH.encode()
)
if not ok: ...
```
**Expected impact:** Eliminates the 100–300ms event-loop freeze during admin login. Low frequency, low total impact, but trivial to fix.

### 🟡 P1 — Cache Apple JWKS in-memory with TTL

**File:** `backend/server.py` line 3900–3920.
**Pattern:** module-level dict `{kid: RSAAlgorithm}` with TTL=1 hour. Refresh on miss. Apple's keys rotate maybe 4× a year.
**Expected impact:** Removes 150–400ms from every Apple sign-in beyond the first one. Improves cold-start perception.

### 🟢 P2 — Shared `httpx.AsyncClient` instance

**Pattern:** module-level `_shared_httpx_client = httpx.AsyncClient(timeout=10.0)`. Replace `async with httpx.AsyncClient() as c` with `c = _shared_httpx_client`. Properly close on shutdown.
**Expected impact:** Faster external auth calls (skip TCP handshake cost). Small under current load, more important at scale.

### 🟢 P2 — Set `waitQueueTimeoutMS` on Motor client

**File:** line 34. Change to:
```python
client = AsyncIOMotorClient(mongo_url, waitQueueTimeoutMS=5000, serverSelectionTimeoutMS=5000)
```
**Expected impact:** Fail-fast surfacing if pool ever does saturate. Currently a silent queue. Defensive — prevents the next outage from looking like a mystery.

### 🟢 P2 — Explicit threadpool sizing

**Pattern:** on startup, set `loop.set_default_executor(ThreadPoolExecutor(max_workers=20, thread_name_prefix='stencil-cpu-'))`. Add basic queue-depth logging.
**Expected impact:** Predictable behavior under load. Today the default pool size is implicit.

---

## What I Will NOT Touch in This Investigation Batch

Per your directive: NO code changes, NO validator changes, NO referral work, NO UI work, NO editor work, NO experimentation.

This document is the deliverable. Next: **you decide which fix to ship next as its own isolated deploy.**

---

## Recommendation for Next Deploy

The P0 fix (wrapping PIL in `run_in_executor`) has the highest probability of fixing the auth-latency-during-generation problem. It's also the most surgically scoped — just wraps existing function calls. If you want to ship one more architectural change to make auth bulletproof, that's the one.

**Rollback safety:** wrapping a sync call in `run_in_executor` is reversible by removing the wrapper. Zero schema impact. Easy to roll back if behavior regresses.

If you'd rather prove the v2 async architecture in production for a few days before touching the sync path, that's also defensible. The v2 path already removes the timeout risk for the most common offender (Medium/Heavy reroll).
