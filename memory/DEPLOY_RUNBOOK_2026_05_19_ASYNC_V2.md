# Deploy Runbook — Build #1: MongoDB-backed Async Stencil Architecture

**Date drafted:** 2026-05-19
**Scope of this deploy:** Single architectural change.
- NEW endpoints: `POST /api/ai-stencil/start`, `GET /api/ai-stencil/status/{job_id}`
- NEW collection: `db.stencil_jobs` (TTL 1h auto-cleanup)
- NEW frontend helper: `regenerateStencilAsync` now points at v2 endpoints with 2s→3s backoff polling
- UNCHANGED: Light reroll (still sync `/api/ai-stencil`), initial generation of all styles (still on legacy `/api/ai-stencil-async`)

## Rollback marker

**Last known-good commit before this deploy:** `36d257e0` (auto-commit before async v2 endpoints landed)

If anything breaks post-deploy:
1. Use the platform **Rollback** button (or git revert in repo) to `36d257e0`.
2. Confirm `/api/ai-stencil/start` returns `404` (gone) and `/api/ai-stencil-async` returns `200` (legacy path restored).
3. Investigate offline. Do NOT re-deploy until root cause is identified.

## Pre-deploy checklist

- [x] Backend reloads cleanly on preview (`[Startup] Ensured TTL index on stencil_jobs.created_at (1h) + unique job_id`).
- [x] Pydantic models reject Light at the validator boundary (422).
- [x] Auth required (401 unauth, 402 zero credits).
- [x] Mongo TTL index on `stencil_jobs.created_at` = 3600s.
- [x] Unique index on `stencil_jobs.job_id`.
- [x] Status endpoint enforces user_id ownership (404 for mismatched / missing).
- [x] Background worker persists status/result/error to MongoDB.
- [x] Regression suite green (12/12 renewal_rollover, 8/8 credit_rollover).
- [x] Frontend `regenerateStencilAsync` rewired to v2 endpoints with 2s → 3s backoff after 6 polls (~12s).
- [x] Light reroll still uses sync `/api/ai-stencil` (no behavior change).

## Production smoke test (run IMMEDIATELY after deploy)

Paste this into a terminal with prod URL set. All 6 assertions must pass before declaring the deploy successful.

```bash
PROD="https://bodybound-subs.emergent.host"
ADMIN_TOKEN=$(curl -s -X POST "$PROD/api/admin-auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"bodyboundstencil@yahoo.com","password":"Body.Bound.Admin.72410"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
DEMO_TOKEN=$(curl -s -X POST "$PROD/api/auth/demo-login" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['session_token'])")
IMG="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

echo "═══ 1: /api/health ═══"
curl -s -w "HTTP:%{http_code}\n" "$PROD/api/health"

echo ""; echo "═══ 2: unauth POST /api/ai-stencil/start → 401 ═══"
curl -s -w "HTTP:%{http_code}\n" -X POST "$PROD/api/ai-stencil/start" \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"medium\"}"

echo ""; echo "═══ 3: light style rejected → 422 ═══"
curl -s -w "HTTP:%{http_code}\n" -X POST "$PROD/api/ai-stencil/start" \
  -H "Authorization: Bearer $DEMO_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"light\"}"

echo ""; echo "═══ 4: zero credits → 402 ═══"
CUR=$(curl -s "$PROD/api/admin/user-lookup?user_id=demo_reviewer_account" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['subscription']['available_credits'])")
curl -s -X POST "$PROD/api/admin/add-credits" -H "Content-Type: application/json" \
  -d "{\"email\":\"reviewer@bodybound.app\",\"credits\":-$CUR}" > /dev/null
curl -s -w "HTTP:%{http_code}\n" -X POST "$PROD/api/ai-stencil/start" \
  -H "Authorization: Bearer $DEMO_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"medium\"}"
curl -s -X POST "$PROD/api/admin/add-credits" -H "Content-Type: application/json" \
  -d "{\"email\":\"reviewer@bodybound.app\",\"credits\":125}" > /dev/null

echo ""; echo "═══ 5: happy path heavy generation ═══"
RESP=$(curl -s -X POST "$PROD/api/ai-stencil/start" \
  -H "Authorization: Bearer $DEMO_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$IMG\",\"style\":\"heavy\",\"auto_enhance\":false}")
echo "$RESP"
JOB_ID=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
echo "Polling..."
for i in 1 2 3 4 5 6 7 8 10 12 15 20 25 30; do
  sleep 2
  ST=$(curl -s "$PROD/api/ai-stencil/status/$JOB_ID" \
    -H "Authorization: Bearer $DEMO_TOKEN" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{d.get(\"status\")} progress={d.get(\"progress\")} has_result={bool(d.get(\"stencil_base64\"))}')")
  echo "  ${i}: $ST"
  echo "$ST" | grep -qE "^completed|^failed" && break
done

echo ""; echo "═══ 6: TTL index in place ═══"
echo "(check Mongo logs / shell — index name should be 'created_at_1' with expireAfterSeconds=3600)"
```

### Expected results

| # | Assertion | Pass criteria |
|---|-----------|---------------|
| 1 | `/api/health` returns 200 | `{"status":"healthy"...}` |
| 2 | Unauthenticated POST | HTTP 401, `"Authorization required"` |
| 3 | Light style rejected | HTTP 422, `string_pattern_mismatch` |
| 4 | Zero credits | HTTP 402, `"No credits available..."` |
| 5 | Heavy completion | Status reaches `completed`, `has_result=True` |
| 6 | TTL index exists | (manual MongoDB shell check, or admin metrics endpoint in future) |

### If any assertion fails

1. STOP all further work.
2. Rollback to `36d257e0`.
3. Open RCA. Do not re-attempt until root cause is documented.

## Post-deploy monitoring (next 24h)

Tail prod logs for these patterns:
- `[AsyncJob-v2:REQ id=...]` — job created
- `[AsyncJob-v2:GEN id=...]` — Gemini call started
- `[AsyncJob-v2:DONE id=...]` — job completed
- `[AsyncJob-v2 <jobid>] Failed:` — job failed (investigate)
- `[CreditGate:v2] Blocked` — zero-credit users hitting the gate

Cross-reference any user reports of "Regeneration Failed" with `[AsyncJob-v2 ...] Failed:` lines using the correlation_id.

## Next deploys (one architectural change each, per discipline rule)

1. **THIS deploy** — Build #1: Async stencil architecture for Medium/Heavy reroll. ← YOU ARE HERE
2. **Next** — Build #2: Auth lifecycle audit + lightweight separation from generation workload. Read-only investigation first, then targeted fixes if any are found.
3. **Then** — Migrate initial-generation path (`generateSingleStyle`) of Medium/Heavy from legacy `/api/ai-stencil-async` (in-memory) to the new `/api/ai-stencil/start` (MongoDB-backed). Currently the in-memory path still works because initial gen happens at app start with low concurrency; not a fire — but eventual consistency is the goal.
4. **Future** — Once all generation traffic is on the v2 endpoints, deprecate and remove `/api/ai-stencil-async`, `/api/ai-stencil-status/{job_id}`, `/api/ai-stencil-job/{job_id}`, and the in-memory `stencil_jobs` dict.
