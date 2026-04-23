# Reroll + Rating feature — branch integration notes

**Shipped to `main` on Apr 23 2026.** This doc exists so that whoever resumes
`redesign/unified-editor` Phase 3 can drop the same behavior into the new
editor UI without rewriting business logic.

## What's shared across both branches
All core logic lives in:

- `frontend/app/lib/stencilApi.ts` — pure API wrappers (no React state, no UI).
  - `regenerateStencil({apiUrl, imageBase64, style})` → `{stencilBase64, processingTimeMs}`
  - `deductCredit(apiUrl, sessionToken)` → `{available_credits, tier, …}`
  - `submitStencilRating({apiUrl, style, rating, sessionToken?})` → void
  - `isFreeRegen(style, freeRegensUsed)` / `regenCostLabel(style, freeRegensUsed)` — UI helpers
  - Constants: `REGEN_COST_CREDITS = 1`, `FREE_REGENS_PER_STYLE = 1`

## Backend contract (already shipped)
- `POST /api/ai-stencil` — with `regenerate_style` set, the server SKIPS its in-memory cache so each reroll produces a fresh Gemini result.
- `POST /api/credits/deduct` — individual user path restored; decrements `available_credits` + increments `credits_consumed_this_cycle`; 402 when out of credits.
- `POST /api/stencil-rating` — body `{style: 'light'|'medium'|'heavy', rating: 'up'|'down', stencil_hash?, prompt_version?}`. Anonymous-friendly (no auth header OK).
- `GET /api/admin/stencil-ratings` — admin-only. Returns `{summary: {light:{up,down}, medium:{…}, heavy:{…}}, totals: {up, down, total, satisfaction_pct}, recent: [...]}`.

## Main-branch UI (live in `app/index.tsx`)
- Regen button already existed — now it:
  - Uses `isFreeRegen(...)` to decide free vs paid.
  - Shows a native `Alert.alert` confirmation on every PAID reroll ("Use 1 Credit"). No silent credit usage.
  - Updates `freeRegenUsed` after the first free regen per style.
  - Clears the rating for that style when regenerated (fresh stencil = fresh rating).
- Inline cost label below each style button (`reroll-cost-light|medium|heavy`) — green "Free reroll" or gold "1 credit".
- Inline thumbs up/down row below the cost label (`rating-{style}-up`, `rating-{style}-down`). Toggling off a rating stops any POST; switching rating sends a new POST.

## What redesign/unified-editor needs to add
Whatever the new editor shows after a style is generated, it needs two tiny components:

### 1. Reroll button + cost label
```tsx
import { regenerateStencil, deductCredit, isFreeRegen, regenCostLabel } from '../lib/stencilApi';

// Reroll flow (pseudo; wire into the unified editor's regen control)
async function onRerollTapped(style) {
  const free = isFreeRegen(style, freeRegenUsed);
  if (!free) {
    if (availableCredits <= 0) { openLowCreditModal(); return; }
    const ok = await confirmAlert('Reroll will cost 1 credit');
    if (!ok) return;
  }
  const { stencilBase64 } = await regenerateStencil({ apiUrl, imageBase64, style });
  // update your store with stencilBase64 + clear any prior rating on this style
  if (free) markFreeRegenUsed(style);
  else await deductCredit(apiUrl, sessionToken);
}
```
Then render `regenCostLabel(style, freeRegenUsed)` as a small label.

### 2. Rating row
```tsx
import { submitStencilRating } from '../lib/stencilApi';
// tiny local state per style: 'up' | 'down' | undefined
// on tap: toggle + if next is 'up' or 'down', POST submitStencilRating({apiUrl, style, rating, sessionToken})
```

## State reset hooks
`stencilRatings` and `freeRegenUsed` both reset at the two spots in `index.tsx`
that clear the workspace (search for `setFreeRegenUsed(new Set())`). The
redesign branch should mirror the same resets.

## Admin visibility
Admin dashboard (`backend/static/admin.html`) now has a "Stencil Quality (Thumbs)"
card on the main Dashboard screen showing satisfaction %, total ratings, and
up/down breakdown per style. No action needed on the redesign branch.

## Tests
See `backend/tests/test_reroll_and_rating.py` for regression coverage (8 cases).
