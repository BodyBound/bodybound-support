# BODY BOUND Stencil Generator — PRD

## Original Problem Statement
Mobile app to convert photos into high-quality "Thermafax-friendly" tattoo stencils.
- Photo → clean, crisp, purely black-and-white line drawings
- Transparent PNG stencils (white pixels removed)
- Edit Mode: Procreate-style layered editor with drawing, erasing, pan/zoom/rotate
- Dark luxury theme

## Architecture
- **Frontend**: Expo (React Native) + TypeScript — single file `/app/frontend/app/index.tsx` (~6400 lines)
- **Backend**: FastAPI + Python — `/app/backend/server.py`
- **AI Model**: `gemini-3-pro-image-preview` via `emergentintegrations`
- **Key libs**: react-native-gesture-handler (RNGH v2), react-native-reanimated v4, react-native-svg 15, expo-image

## What's Been Implemented

### 2025-02 (Session 1-3)
- Core stencil generation (light/medium/heavy styles)
- Transparent PNG post-processing (white → transparent)
- Fixed `ph://` crash on iOS with expo-image
- Edit Mode: pan/zoom/rotate canvas, drawing, erasing, opacity control
- Layer system: reference photo + transparent stencil + SVG drawings
- Reverted backend to "Feb 16" high-quality prompt

### 2026-02-27 (Current Session)
- **P0 FIXED**: Reference photo disappears on 2nd Edit Mode entry
  - Root cause: `saveEditedStencil` merged canvas to opaque PNG, overwrote stencil
  - Fix: `openEditMode` now uses `stencilVersions[selectedVersion]` (original transparent PNG) not merged `stencilImage`
  - `originalAIStencil` explicitly set in `generateSingleStyle`
- **Pencil Lag (P1)**: Multiple optimization passes:
  - Moved path accumulation from React state → Reanimated SharedValue (UI thread)
  - Replaced `continueDrawing` runOnJS-per-frame with `useAnimatedProps` + JSI (New Arch)
  - **Removed StreamLine smoothing** (was causing visible 3-frame visual gap)
  - Net: path now tracks pencil with no visual gap (cursor = path tip)
- **Layout Restructured**:
  - Removed `ScrollView` wrapper
  - `imageArea: flex:1` fills all available space above buttons
  - `bottomBar` contains all controls (style buttons + source buttons)
  - Image fills screen, buttons at very bottom
  - Style buttons responsive: `Math.min(80, (SCREEN_WIDTH-80)/3)` for iPad
- **Yellow Regen Hint Text**: Added golden italic text below style buttons
- **Rate & Share row removed** (maximizes image space)

## Key State Variables
- `referencePhotoLayer`: Set on stencil generate, never cleared on edit save — the original photo for edit mode
- `originalAIStencil`: Set on generate, used as `editModeStencilImage` (transparent base)
- `currentPathSV`: SharedValue accumulates live stroke on UI thread
- `animatedStrokeProps`: drives AnimatedSVGPath.d via JSI (New Arch, zero bridge)
- `enableFPSV`: SharedValue synced to enableFingerPainting state for gesture worklets

## Pending / In-Progress

### P1 — Drawing Lag
- Current state: path updates via `useAnimatedProps` + JSI (New Arch)
- No smoothing during drawing (removed for responsiveness)
- If still laggy after reload: ultimate fix = dev build + react-native-skia
- Note: `newArchEnabled: true` in app.json

### P2 — Crop Tool Inaccuracy
- `handleApplyCrop` function needs investigation
- Calculations for `cropData` may be off

### P2 — iPad Style Button Sizes
- Partially fixed (responsive sizing formula added)
- May need further tweaking based on user feedback

## Future / Backlog
- P3: Refactor `index.tsx` (6400+ lines → components)
- P4: Refactor `server.py`
- P5: "Save to App" Gallery feature

## Key API Endpoints
- `POST /api/ai-stencil-async` — generate stencil (style: light/medium/heavy)
- `GET /api/ai-stencil-status/:jobId` — poll generation status
- `POST /api/make-transparent` — make image transparent

## Credentials
- GOOGLE_API_KEY in `/app/backend/.env`

## Important Notes
- `newArchEnabled: true` → Fabric, so setNativeProps is unreliable; use useAnimatedProps
- Metro in CI mode: no hot reload — user must shake device → Reload in Expo Go after updates
- DO NOT change backend AI model/prompt (quality is dialed in)
- Backend stencil generation uses: `gemini-3-pro-image-preview` model
