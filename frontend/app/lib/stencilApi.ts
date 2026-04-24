/**
 * Shared stencil service — used by BOTH `main` UI (index.tsx) and
 * `redesign/unified-editor`. Pure API calls only. Callers decide how to
 * render results and handle state.
 *
 * Keep this file UI-free. No React imports. No state.
 */

export type StencilStyle = 'light' | 'medium' | 'heavy';
export type Rating = 'up' | 'down';

export const REGEN_COST_CREDITS = 1;
/** Number of FREE rerolls granted per style before credits start being charged. */
export const FREE_REGENS_PER_STYLE = 1;

export interface RegenerateParams {
  apiUrl: string;
  imageBase64: string;        // data URL or raw base64
  style: StencilStyle;
  token?: string;             // optional auth token — enables server-side credit gate
}

export interface RegenerateResult {
  stencilBase64: string;      // data URL from backend
  processingTimeMs: number;
}

/** Call `/api/ai-stencil` with `regenerate_style` — backend skips its cache. */
export async function regenerateStencil(
  params: RegenerateParams,
): Promise<RegenerateResult> {
  const { apiUrl, imageBase64, style, token } = params;

  // Normalise to data URL (the backend accepts both, but this keeps client code uniform)
  const normalised = imageBase64.startsWith('data:')
    ? imageBase64
    : `data:image/jpeg;base64,${imageBase64}`;

  const shadingDetail = style === 'light' ? 5 : style === 'medium' ? 30 : 50;
  const solidFill = style === 'heavy' ? 30 : 0;

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(`${apiUrl}/api/ai-stencil`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      image_base64: normalised,
      style: 'tattoo',
      line_color: 'black',
      shading_detail: shadingDetail,
      solid_fill: solidFill,
      regenerate_style: style,
    }),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`regenerateStencil ${resp.status}: ${text}`);
  }
  const data = await resp.json();
  return {
    stencilBase64: data.stencil_base64,
    processingTimeMs: data.processing_time_ms,
  };
}

export interface DeductCreditResult {
  available_credits: number;
  total_monthly_credits?: number;
  tier: string;
  is_studio_team?: boolean;
}

/** Deduct 1 credit via `/api/credits/deduct`. Throws on non-200. */
export async function deductCredit(
  apiUrl: string,
  sessionToken: string,
): Promise<DeductCreditResult> {
  const resp = await fetch(`${apiUrl}/api/credits/deduct`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${sessionToken}`,
      'Content-Type': 'application/json',
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`deductCredit ${resp.status}: ${text}`);
  }
  return resp.json();
}

export interface SubmitRatingParams {
  apiUrl: string;
  style: StencilStyle;
  rating: Rating;
  sessionToken?: string;      // Optional — anonymous ratings are allowed
  stencilHash?: string;       // Optional dedupe key (e.g. first 32 chars of base64)
  promptVersion?: string;     // Optional tag for prompt version
}

/** POST a thumbs up/down rating. Low-friction, non-blocking — errors are logged
 * by the caller but should never interrupt the editing flow. */
export async function submitStencilRating(
  params: SubmitRatingParams,
): Promise<void> {
  const { apiUrl, style, rating, sessionToken, stencilHash, promptVersion } = params;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (sessionToken) headers['Authorization'] = `Bearer ${sessionToken}`;
  const resp = await fetch(`${apiUrl}/api/stencil-rating`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      style,
      rating,
      stencil_hash: stencilHash,
      prompt_version: promptVersion,
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`submitStencilRating ${resp.status}: ${text}`);
  }
}

/** Predicate: is this regen FREE (first for the style) or does it cost credits? */
export function isFreeRegen(
  style: StencilStyle,
  freeRegensUsed: ReadonlySet<string>,
): boolean {
  return !freeRegensUsed.has(style);
}

/** Human label for the regen button cost hint. */
export function regenCostLabel(
  style: StencilStyle,
  freeRegensUsed: ReadonlySet<string>,
): string {
  return isFreeRegen(style, freeRegensUsed)
    ? 'Free reroll'
    : `${REGEN_COST_CREDITS} credit`;
}
