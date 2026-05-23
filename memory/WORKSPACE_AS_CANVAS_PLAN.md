# Workspace = Canvas Plan — Next Session

**Drafted:** May 22 2026 (session end, baby crying, deferring per user agreement)
**Owner intent (direct quotes):**
- "I want when they pick the reference photo, I want that to open up in the editing module. That will be the workspace, that will be the landing page from here on out, the Procreate Canvas stuff."
- "I want the generate buttons to function exactly how they were functioning on the original landing screen. So if they generated more than one, we had the arrow so they could go through and look at the ones that they have selected before. They could thumbs up it, they could thumbs down it, all of that."
- "I want them to be able to edit their reference before even generating the stencils. So I want them to be able to erase, I want them to be able to add if they need to. I want them to be able to up the contrast, sharpness, things like that."

---

## Architectural shift

**OLD model:**
- Landing page (image preview + buttons) → tap Edit → opens fullscreen edit modal
- Edit modal is a SECONDARY screen for refining a stencil

**NEW model:**
- Landing page (no image, just Gallery/Camera buttons) → pick image → IMMEDIATELY enter fullscreen edit modal
- Edit modal IS the primary working surface; landing only exists as empty state
- Generation, history nav, ratings, reroll all live INSIDE the edit modal
- Reference prep (contrast, sharpness, erase, brush) happens BEFORE generation, inside the same canvas

---

## Implementation in order (sized for one focused session)

### Step 1: Auto-open edit modal on image pick (5 min, low risk)

Trigger `openEditMode()` inside the `pickImage` and `takePhoto` success branches, after `setOriginalImage(...)`. The existing `openEditMode` already handles null stencil — it'll just show the reference photo full-screen with no overlay until a stencil is generated.

**File:** `frontend/app/index.tsx`
**Risk:** very low. `setShowEditModal(true)` is already proven safe.
**Caveat:** check whether `openEditMode` early-returns or warns when `transparentBaseStencil` is null. If it does, soften the guard or add a "no-stencil-yet" branch that skips the stencil-related setters.

### Step 2: Bottom generation dock inside the edit modal (1-2 hr)

Re-mount the existing `stencilStyleSection` JSX (from index.tsx around line 4454) inside the edit modal, anchored to the bottom of the canvas using `position: 'absolute'` over the gesture layer. Wrap in a translucent dark band so it doesn't fight the canvas.

**Must preserve:**
- `generateSingleStyle('light' | 'medium' | 'heavy')` handlers — exact same
- `regenerateSingleStyle()` — exact same
- History nav arrows `goBackInHistory(style)` / `goForwardInHistory(style)`
- Thumbs up/down: `rateStencil(style, 'up' | 'down')`
- Reroll cost labels: `regenCostLabel()`, `isFreeRegen()`
- The "stencilButtonImage" thumbnails — but these are CDN-loaded; need fallback if URLs 404 in TestFlight (already noted earlier as a separate diagnostic)

**Risk:** medium. The stencil section has 7+ branches (no stencil / stencil exists / regenerating / rating active / etc). Carefully port without simplifying.

### Step 3: Top pulldown ≡ menu inside the canvas (30 min)

Move the workspace pulldown I built in Phase 1 (currently rendered on the landing page) INSIDE the edit modal render tree. It hosts Gallery / Camera / Start Over / Settings. Same handlers.

**State to keep:** `workspaceMenuOpen` (boolean)
**State to remove from current location:** the landing-page-level chips + pulldown (after this lands, they're dead code on the landing page).

### Step 4: Closing the edit modal = back to landing only via "Start Over"

The edit modal currently has a "Done" button. Now:
- "Done" → save drawings, but stay in the canvas (because there's no other place to go)
- "Start Over" (from pulldown) → `resetWorkspaceState()` + `setShowEditModal(false)` → user lands back on the empty landing page

### Step 5: Reference prep tools (its own deploy, do AFTER Step 1-4 are baked)

New state needed:
- `referenceAdjustments: { contrast: 0, sharpness: 0, brightness: 0 }` (slider values -1.0 to +1.0)
- `referenceBrushPaths: SkiaPath[]` — separate from existing `drawingPaths` (which paint on the stencil)

New UI inside canvas:
- Left tray (slide-out) with 3 sliders + erase/draw toggles for the reference layer
- When user adjusts, apply via CSS-like transforms to the reference Image component OR via a Canvas filter pass before sending to AI generation

**Risk:** medium-high. Adjustments need to apply BEFORE the base64 is sent to `/api/ai-stencil`. That means a new pre-processing step on the client (PIL doesn't exist in RN — would use Skia or expo-image-manipulator).

### Step 6: Clean up Phase 1 chips on landing page (10 min, cosmetic)

After Step 2+3 land, the floating ≡ chip and ✂ chip on the LANDING page (when `originalImage` exists pre-edit-modal-open) become dead code — the user never sees the landing page with an image now. Remove the workspace-mode style overrides on the landing-page render. The landing page becomes purely the empty state.

---

## Regression checklist for the implementation session

Before merging Steps 1-4:
- [ ] Pick image from Gallery → edit modal opens automatically
- [ ] Pick image from Camera → edit modal opens automatically
- [ ] Light button inside canvas generates light stencil; overlay appears
- [ ] Medium button → async v2 polling works inside modal
- [ ] Heavy button → async v2 polling works inside modal
- [ ] After 2 Light generations, history arrows navigate between v1 and v2
- [ ] Thumbs up/down work on each version
- [ ] Reroll cost label updates correctly (free first reroll, then paid)
- [ ] Hold-to-compare still works
- [ ] Eraser still works (on stencil, not reference yet)
- [ ] Opacity slider still works
- [ ] Done button saves drawings without crashing
- [ ] Start Over from pulldown resets to landing page
- [ ] All existing modals still accessible (settings, paywall, crop, low-credit, milestone)
- [ ] Auth/Subscription/RC untouched
- [ ] `git diff --stat backend/` empty
- [ ] TypeScript error count unchanged (currently 25)

---

## State variables already in place (no new state needed for Steps 1-4)

- `originalImage`, `stencilImage`, `stencilVersions`, `stencilHistory`, `stencilHistoryIndex`
- `selectedVersion`, `isGeneratingAI`, `regeneratingStyle`
- `editModeOriginalImage`, `editModeStencilImage`, `editOpacity`, `brushSize`, `isEraser`
- `drawingPaths`, `currentPath`
- `showEditModal`, `workspaceMenuOpen`, `showWorkspaceTooltip`
- `stencilRatings`, `freeRegenUsed`, `freeStyleChangeUsed`

## State variables NEW for Step 5 only (reference prep)

- `referenceAdjustments: { contrast: number, sharpness: number, brightness: number }`
- `referenceBrushPaths: SkiaPath[]`
- `referencePrepTrayOpen: boolean`

---

## Risk mitigation

- Land Steps 1-4 as ONE deploy, isolated from Step 5.
- Have rollback point before deploy (record commit hash in next session's runbook).
- Per "deployment discipline" rule established earlier this session.

---

## What stays untouched (per long-standing user directive)

- Backend (server.py, all routes)
- RevenueCat / subscriptions / credits / paywall
- Auth / session
- Async architecture / polling / v2 endpoints
- Validator behavior
- Generation prompts / pipeline timing
- API contracts
- Background workers
- Telemetry

---

## Estimated session size

- Steps 1-4: ~1 focused session (4-6 hr of careful coding + 1 hr regression). Single deploy.
- Step 5 (reference prep): its own separate session and deploy.

**Both should be done with FRESH context** — not at the tail of a long session like this one.
