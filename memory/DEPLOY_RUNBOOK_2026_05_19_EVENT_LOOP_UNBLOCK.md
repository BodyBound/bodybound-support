# Deploy Runbook — Stability Batch: PIL + LiteLLM Event-Loop Unblocking

**Date drafted:** 2026-05-19 (after v2 async deploy + auth audit)
**Scope:** Single stability batch. One architectural pattern (push blocking CPU/LLM work to thread executors), applied at the audited call sites only.
**Goal:** Auth endpoints stop freezing for ~15s during active stencil generation.

## What changed

### PIL fix (per audit)
- New async wrappers `post_process_stencil_async` and `enhance_photo_basic_async` near the sync defs.
- 12 call sites converted to `await ..._async(...)`. Only the one inside sync helper `enhance_photo_for_ai` (line 1185) intentionally left as-is.

### LiteLLM / genai SDK fix (scope expansion after concurrency test proved PIL alone wasn't enough)
- New helper `_run_llm_coro_in_thread(coro_factory)` — runs an async LLM coroutine inside a worker thread with its own private asyncio loop, so blocking sync calls (`litellm.completion`, `client.models.generate_content`) inside library code stop freezing the main event loop.
- 2 call sites wrapped:
  - `generate_with_gemini` line ~2294: `chat.send_message_multimodal_response(msg)` → `_run_llm_coro_in_thread(lambda: chat.send_message_multimodal_response(msg))`
  - `enhance_photo_with_ai` line ~1138: `client.models.generate_content(...)` → `loop.run_in_executor(None, lambda: client.models.generate_content(...))`

### Out of scope (explicitly NOT changed)
- No frontend changes
- No auth handler logic changes
- No validator behavior changes
- No subscription / credit / purchase flow changes
- No bcrypt / JWKS / httpx / Motor changes (deferred per discipline rule)
- The 3rd LlmChat usage at line 1661 is a diagnostic endpoint (not hot path) — unchanged

## Rollback marker

**Last known-good commit before this deploy:** `2b909d6c` (auto-commit before PIL fix landed). Verify with `git log --oneline -10` before deploy.

If anything breaks post-deploy:
1. Use the platform **Rollback** button → `2b909d6c`.
2. Confirm Light sync gen still returns 200.
3. Investigate offline. Do NOT re-deploy until root cause documented.

## Pre-deploy verification (already passed on preview)

- ✅ Backend reloads clean. No import errors. Startup logs show all TTL indexes present.
- ✅ Light sync gen returns 200 with stencil (~15s — unchanged).
- ✅ Medium v2 async start → poll → completed (~10s, `has_result=True`).
- ✅ Heavy v2 async: same.
- ✅ Backend regression suite: renewal_rollover 12/12, credit_rollover 8/8.
- ✅ Memory: backend RSS 27 MB, no leak after multiple gens.
- ✅ Recent backend logs: no new 5xx, no new exceptions, no `[AsyncJob-v2] Failed`.
- ✅ **CRITICAL — concurrent auth/me during heavy gen:**
  - **Before this deploy:** 12 parallel `/api/auth/me` probes all stuck at exactly ~15.8 seconds during gen.
  - **After this deploy:** 12 parallel probes returned in 0.27–0.58s (median 345ms, p90 534ms).
  - **45× faster.** Event loop is no longer blocked by LLM round-trips.

## Production smoke test (run IMMEDIATELY after deploy)

```bash
PROD="https://bodybound-subs.emergent.host"
DEMO_TOKEN=$(curl -s -X POST "$PROD/api/auth/demo-login" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['session_token'])")
IMG="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

echo "═══ 1: /api/health 200 ═══"
curl -s -w "HTTP:%{http_code} time:%{time_total}s\n" "$PROD/api/health"

echo "═══ 2: /api/auth/me 200 (cold) ═══"
curl -s -w "HTTP:%{http_code} time:%{time_total}s\n" "$PROD/api/auth/me" -H "Authorization: Bearer $DEMO_TOKEN" -o /dev/null

echo "═══ 3: Light sync gen still works ═══"
curl -s -w "HTTP:%{http_code} time:%{time_total}s\n" \
  -X POST "$PROD/api/ai-stencil" \
  -H "Authorization: Bearer $DEMO_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"tattoo\",\"line_color\":\"black\",\"shading_detail\":5,\"solid_fill\":0,\"regenerate_style\":\"light\"}" \
  -o /tmp/p_light.json
echo "  has_stencil: $(python3 -c "import json;d=json.load(open('/tmp/p_light.json'));print(bool(d.get('stencil_base64')))")"

echo "═══ 4: Heavy async gen completes ═══"
RESP=$(curl -s -X POST "$PROD/api/ai-stencil/start" \
  -H "Authorization: Bearer $DEMO_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"heavy\",\"auto_enhance\":true}")
JOB_ID=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
echo "  job_id=$JOB_ID"
for i in 1 2 3 4 5 6 7 8 10 12 15 20 25 30 40; do
  sleep 2
  ST=$(curl -s "$PROD/api/ai-stencil/status/$JOB_ID" -H "Authorization: Bearer $DEMO_TOKEN" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{d.get(\"status\")} progress={d.get(\"progress\")}')")
  echo "  poll@~${i}*2s: $ST"
  echo "$ST" | grep -qE "^completed|^failed" && break
done

echo "═══ 5: CRITICAL — concurrent auth/me during fresh heavy gen ═══"
RESP=$(curl -s -X POST "$PROD/api/ai-stencil/start" \
  -H "Authorization: Bearer $DEMO_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"heavy\",\"auto_enhance\":true}")
JOB_ID=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
sleep 1
for i in $(seq 1 12); do
  ( curl -s --http1.1 -H "Connection: close" -o /dev/null \
      -w "  probe $i: HTTP=%{http_code} time=%{time_total}s\n" \
      "$PROD/api/auth/me" -H "Authorization: Bearer $DEMO_TOKEN" ) &
done
wait
echo "  EXPECTED: all probes return in <2s (was ~15.8s before this deploy)"
```

### Pass criteria (ALL must pass)

| # | Assertion | Pass criteria |
|---|-----------|---------------|
| 1 | health | HTTP 200, time < 1s |
| 2 | auth/me cold | HTTP 200, time < 1s |
| 3 | Light sync | HTTP 200, `has_stencil=True` |
| 4 | Heavy async | status reaches `completed`, has result |
| 5 | **Concurrent auth/me during gen** | **all 12 probes < 2s** (was ~15.8s) |

### If any assertion fails

1. STOP all further work.
2. Rollback to `2b909d6c`.
3. Open RCA before re-attempting.

## Post-deploy monitoring (next 24h)

Tail prod logs for:
- `[AsyncJob-v2:REQ id=...]` job created
- `[AsyncJob-v2:DONE id=...]` job completed
- `[AsyncJob-v2 ...] Failed:` → investigate
- Memory: `ps aux | grep uvicorn` — backend RSS should stay under 500MB; watch for steady climb (would indicate thread-pool worker leak)
- Auth complaints: should drop to zero during active generation periods

## Why this is reversible / low-risk

- `run_in_executor` is a stdlib primitive — same pattern already in use for the validator (added May 6 stability patch). Proven safe under prod.
- The new thread-pool execution path produces **identical return values** to the old direct execution — just delivered via a different concurrency primitive. No data shape changes, no schema changes.
- If a worker thread itself crashes, the future raises an exception and the caller's `await` raises — same error path as before.
- Default uvicorn worker thread pool is sized at ~40 threads; we use at most 1 per active LLM call. Plenty of headroom.

## Files changed

- `backend/server.py`:
  - Added `post_process_stencil_async`, `enhance_photo_basic_async`, `_run_llm_coro_in_thread` helpers.
  - 13 sync call sites → async wrapper calls (4 post_process, 9 enhance_basic across 3 paths).
  - 2 LLM call sites pushed to worker thread (`generate_with_gemini`, `enhance_photo_with_ai`).
- **No frontend changes.**
- **No schema / config / .env changes.**

## Next deploys (after this lands and bakes)

Per audit + discipline rule, each is its own isolated deploy:
1. (P1) Bcrypt admin login wrap in executor + Apple JWKS in-memory cache.
2. (P2) Shared `httpx.AsyncClient`; Motor `waitQueueTimeoutMS=5000`; explicit ThreadPoolExecutor sizing.
3. (Eventually) migrate initial-gen Medium/Heavy from legacy in-memory `/api/ai-stencil-async` to v2 endpoints; deprecate the in-memory path.
4. (~May 26) re-examine soft-log distribution after 7 days of fresh data; recalibrate validator if appropriate.
