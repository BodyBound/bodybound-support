# Post-Mortem — May 6, 2026 Production Backend Outage

**Severity:** P1 — total production unavailability
**Customer impact:** All paid users could not sign in or generate stencils for ~30+ minutes
**Trigger:** User-reported "Google Sign-In failed" on the production iOS build

---

## Timeline (UTC)

| Time | Event |
|---|---|
| ~14:30 | Wrong-reference validator + comp-credits + timing instrumentation deployed to production. App marked Apple-approved earlier in the day. |
| ~16:00 | First user (Ringo) reports repeated Medium-stencil failures — sends video. Investigation shows validator hard-block with `edge_ncc=0.0, line_precision=0.594` rejecting legit Gemini outputs. |
| ~16:15 | Validator switched to **soft-log mode** — runs but never blocks. Hotfixed and deployed. Production confirmed healed end-to-end. |
| ~17:30 | User sends second screenshot — "Google Sign-In Failed" alert on iPad. |
| 17:35 | Investigation: `POST /api/auth/google-session` returns **HTTP 520** from Cloudflare. Polled `/api/health` — also 520. **Production backend is fully unreachable.** |
| 17:35–18:00 | 90+ seconds of continuous 520s. Restart not initiated yet. |
| 18:00 | User initiates restart/redeploy. Polling continues. |
| ~18:42 | Polling shows recovery at attempt 21 (~2 min after restart). `/api/health` returns 200. |
| 18:43 | Full verification suite passes: health, login, AI stencil. |
| 18:50 | First post-recovery generation runs ~46s server-side, ~99s wire-time (cold container). |
| 19:01 | Concurrent-load test (3 simultaneous stencils) reveals Gemini latency triples under concurrency (22s → 65s), blowing through Cloudflare's ~60s edge proxy timeout. Backend serves all 3 successfully but client sees 502s. |
| 19:09 | 3 pre-flight stability fixes applied to preview, validated, ready to deploy. |

---

## Root Cause

**The production FastAPI process became unresponsive (Cloudflare 520) for an extended period.** Without container shell access, definitive cause-of-death cannot be confirmed, but evidence points to one of:

### Most likely (60%): Memory exhaustion / OOM kill

Today's earlier deploy added several memory-hungry behaviors layered on top of an already-leaky base:

1. **Unbounded in-memory `stencil_cache`** — dict of base64 strings, ~700 KB per entry, no LRU eviction, capped at 50 entries by count but old code took the *first* key which was insertion-order, not LRU
2. **New `validator_softlog` collection writes** — every wrong-reference miss writes a row + reads the buffer with `count_documents` followed by per-row `delete_one` calls
3. **`paywall_telemetry` rolling buffer** — same `count_documents` + per-row delete anti-pattern
4. **Stencil base64 payloads** held in async handler scope across slow Gemini calls (20-65s) — multiple in-flight requests = multiple resident copies

Combined, under normal traffic + a couple concurrent users this could push the container past its memory ceiling. OOM-killer terminates the process. Cloudflare 520 with no graceful shutdown signature is consistent with OOM-kill.

### Secondary (25%): Mongo connection pool exhaustion

The new soft-log writes + telemetry writes happen in series on the request path. Under concurrency, the Mongo client's connection pool could max out, causing all subsequent requests to hang indefinitely. Cloudflare gives up after its idle timeout → 520.

### Tertiary (15%): asyncio event loop starvation from sync work in async handlers

The validator was running `cv2.Canny` + numpy ops directly in the async handler (no `run_in_executor`). Under concurrent load, a single ~200 ms blocking call can starve the event loop, queueing all other requests. Symptom would be slow degradation rather than full crash, but possible co-factor.

---

## What Failed

1. **Wrong-reference validator was over-aggressive** in production. Calibration thresholds (`edge_ncc < 0.12 AND line_precision < 0.86`) were tuned against pre-rendered reference stencils, but real-time Gemini output produced systematically different metrics — `edge_ncc=0.0` was the dominant case, meaning **every Medium output today scored as a wrong-reference rejection**. This caused Ringo's "retry over and over" experience and was the trigger for the day's debugging chain.
2. **Production crashed silently** — no alerting, no automatic recovery. We learned about the outage through a customer screenshot.
3. **No memory pressure monitoring** in place. Cannot confirm OOM definitively.
4. **Validator's CPU work blocked the event loop** under concurrency — confirmed via parallel-completion timestamps after fix.
5. **Cloudflare 60s proxy timeout** is a hard ceiling we hadn't measured against. Concurrent Gemini calls take 65s+, making sync architecture fragile beyond ~3 simultaneous users.

---

## What Was Fixed

### Already in production

1. **Validator soft-log mode** (deployed ~16:15)
   - Validator runs but never blocks
   - Would-have-failed cases logged + persisted to `validator_softlog` rolling buffer
   - No 502 rejections, no credit refunds based on validator
   - Production unblocked for paid users
2. **Manual restart** (deployed ~18:42) — restored backend availability after 520 outage

### Pre-flight stability fixes (this deploy)

3. **True LRU eviction for `stencil_cache`**
   - Migrated to `collections.OrderedDict`
   - HIT bumps entry to MRU position; SET evicts LRU on overflow
   - Cap reduced from 50 → 30 (≈21 MB worst-case footprint)
4. **Validator off the asyncio event loop**
   - New `validate_stencil_reference_match_async` wraps the sync function via `loop.run_in_executor(None, ...)`
   - Concurrent stencils now genuinely served in parallel by the backend
5. **Single-query rolling-buffer pruning**
   - Both `validator_softlog` and `paywall_telemetry` switched from `count_documents` + per-row `delete_one` to a single `find ... skip(200) ... limit(1)` cutoff lookup followed by one `delete_many({timestamp: {$lte: cutoff}})`
   - Eliminates per-row Mongo round-trips under load

### Verification

- 5 sequential generations on preview: HTTP 200, all under 30s, **memory flat at 150 MB throughout**
- Concurrent 3-generation test: backend served all 3 successfully (event loop unblocked confirmed)
- All admin endpoints returning 200
- LRU cache size capped at 30 entries
- Soft-log buffer prune passes single-query test

---

## Prevention Steps

### Already implemented today
- Cron health-check (`/api/health` validation in monthly_refresh.yml) catches BACKEND_URL drift before it silently breaks the credit-refresh job
- Soft-log mode for validator → no more user-visible rejections from this class of bug

### Going into this deploy
- LRU eviction → bounded memory growth
- run_in_executor → event loop never blocks on CPU work
- Single-query buffer pruning → bounded Mongo round-trips per request

### Recommended follow-ups (not in this deploy)

1. **Memory monitoring** — add `/api/admin/memory-stats` endpoint exposing process RSS so admin dashboard can show trend. Alert if RSS climbs >300 MB over a 1h window.
2. **Async polling architecture for Medium/Heavy stencils** — Gemini latency under concurrency exceeds Cloudflare's 60s edge proxy timeout. Switch to async job + polling for these styles. **Confirmed needed today** via concurrent-load test.
3. **Universal Key balance monitor** — add a 1× per hour cron beacon hitting Gemini with a 1-pixel dummy image. Alert if response is 403 / FREE_USER_EXTERNAL_ACCESS_DENIED. Brian's Key dropped to 3.74 credits during today's incident — would have been a separate outage if not topped up.
4. **Validator hard-block recalibration** — currently in soft-log. After 7 days of real production telemetry from `validator_softlog`, recalibrate `edge_ncc` and `line_precision` thresholds against actual Gemini-output distribution. Then re-enable hard-block + retry + 502+refund flow.
5. **Container memory ceiling visibility** — request memory limits + OOM events from the Emergent platform UI so we can confirm/refute OOM as today's actual cause.
6. **Per-deploy smoke test** — automate a 3-call sequence (health, admin login, one stencil) immediately after each production deploy. Fails fast on regressions.

---

## Validator Recalibration Window

**Soft-log buffer cleared (`cleared_at`):** May 19, 2026 (post-alpha-fix deploy)

**Why cleared:** The 10 entries in the buffer before this date were produced by
the buggy pre-fix validator that always returned `edge_ncc=0.0` due to PIL
discarding the alpha channel during RGBA→L conversion on real Gemini PNG
stencils. The numbers were mathematically meaningless and would have skewed any
threshold recalibration.

**Fix shipped:** `_decode_for_validation` helper added — composites RGBA over
white before grayscale conversion. Verified live: legit Gemini Medium stencils
now produce `edge_ncc` in the **0.22–0.37** range and `line_precision` in the
**0.93–0.97** range, matching offline calibration. Wrong-reference pairs land
at `edge_ncc < 0.05` and `line_precision < 0.80`.

**Recalibration window:** 7 days from clear (target Tue May 26, 2026). During
this window the validator runs in soft-log mode only — no user-facing block,
no refund, no retry. After 7 days of real production data we re-examine the
distribution and decide whether to re-enable hard-block with calibrated
thresholds, or stay in soft-log indefinitely.

**Do NOT re-enable hard-block before:**
1. ≥ 100 fresh soft-log events accumulated post-fix
2. The edge_ncc / line_precision distributions are reviewed against actual
   user-reported quality complaints (do flagged stencils correlate with
   complaints?)
3. Thresholds are re-tuned against the new distribution

---

## Customer Communication

- **Ringo (`ringopiniontattoo@gmail.com`)** — primary affected user with video evidence. **Comp 25 credits** via `POST /api/admin/comp-credits` after this deploy lands. Suggested message: "Confirmed your account, found the bug — fixed. Comping 25 credits as apology. Try again now."
- **Other paid users active during the outage window** — pull list from access logs and offer comp credits proactively.

---

## Files Touched

- `backend/server.py` — validator soft-log mode, LRU cache, run_in_executor wrapper, single-query buffer pruning, `/api/admin/comp-credits`, `/api/admin/comp-credits-history`, `/api/admin/validator-softlog`, `/api/admin/duplicate-sub-audit`, `/api/admin/purchase-guard-metrics`, `/api/admin-tool/conversion-funnel`, webhook schema enrichment with `user_id`/`product_id`
- `frontend/app/screens/PaywallScreen.tsx` — pre-purchase + post-purchase entitlement sync, `[RC:BLOCK_PURCHASE]` log lines, structured beacons, "Active Subscription Detected" alert + Apple Settings deep link
- `.github/workflows/monthly_refresh.yml` — `/api/health` pre-flight check
- `backend/tests/test_wrong_reference_validator.py` — 19/19 calibration test (kept for post-recalibration use)

---

## Outstanding Risks

- Universal LLM Key balance can still drop unexpectedly. Auto-recharge threshold should be raised manually in Brian's Emergent profile.
- Concurrent users >3 will see 502s from Cloudflare's edge proxy until async polling lands. Mitigation: async-polling architecture is now P0 for Medium/Heavy.
- Today's actual cause-of-death (OOM vs Mongo pool vs other) remains unconfirmed without container-level telemetry. The 3 fixes deployed today address the 3 most likely candidates but do not rule out a 4th.
