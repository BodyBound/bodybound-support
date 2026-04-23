"""Pre-Scan Visual Demo — v3 (Constraint-Only + Variance Test).

Purpose of this pass:
  The user has asked us to reassess whether pre-scan should exist at all.
  Pre-scan is now a pure NEGATIVE-CONSTRAINT block (what the model is
  forbidden to do). There is NO classification step, NO stylistic guidance,
  NO per-category rules — all of those were acting as weak prompt modifiers.

What the constraint block contains:
  - structural preservation (count, pose, orientation, framing, gaze, identity)
  - explicit line-hierarchy preservation (no softening, no blurring)
  - explicit black-fill rule (do not introduce new solid black regions unless
    they are directly derived from the reference's own solid-black structure)
  - an explicit "do not override the base prompt" clause

Variance test:
  Each reference is generated TWICE in each condition (WITH preamble and
  WITHOUT preamble) at temperature=0 via /api/ai-stencil. A pixel-level
  mean-absolute-difference between the two runs is written alongside the
  PNGs — lower = more consistent. If pre-scan does not measurably reduce
  variance, it earns no place in the production pipeline.

Usage:
    python scripts/prescan_visual_demo.py
"""
import asyncio, base64, json, os, time
import httpx
from io import BytesIO
import numpy as np
from PIL import Image

BACKEND = "http://127.0.0.1:8001"

IMAGES = {
    "skull": "/app/backend/static/portrait3.jpg",
    "lion": "/app/backend/static/portrait4.jpg",
}

# ---------------------------------------------------------------------------
# Pre-scan is a pure NEGATIVE-CONSTRAINT block. No guidance, no interpretation.
# Nothing here tells the model HOW to draw. It only tells it what it MUST NOT
# do. The base prompt remains the single authority on line weight, density,
# and hierarchy.
# ---------------------------------------------------------------------------
CONSTRAINT_BLOCK = """PRE-SCAN CONSTRAINTS. The rules below are NEGATIVE CONSTRAINTS only.
They do not suggest a style, do not describe how to render the stencil, and
must not override any rule in the base prompt. If any rule here conflicts
with the base prompt's line-weight, density, or hierarchy rules, the base
prompt wins.

YOU MUST NOT:
- Change the subject count. Do not duplicate, mirror, pair, tile, or split-panel the subject.
- Change the pose, head tilt, body posture, orientation, facing direction, framing, crop, or gaze direction shown in the reference.
- Replace, reinterpret, or regenerate the subject's identity. Only trace what is visibly in the reference.
- Introduce any new solid black region that is not directly derived from a solid-black region already present in the reference photo. Solid-black output pixels must have a solid-black source counterpart. When in doubt, use line work instead.
- Soften, blur, denoise, smooth, or normalize edges. Do not reduce edge sharpness below what the reference shows.
- Collapse fine detail into uniform noise. Strong contours in the reference must remain strong; mid-detail must remain readable.
- Weaken, override, or replace any line-weight, density, or hierarchy rule that the base prompt specifies. This block adds constraints only."""


async def gen(client: httpx.AsyncClient, image_b64: str, preamble: str | None, out_path: str) -> None:
    body = {
        "image_base64": image_b64,
        "line_color": "black",
        "regenerate_style": "heavy",
        "temperature": 0.0,
    }
    if preamble:
        body["extra_preamble"] = preamble
    r = await client.post(f"{BACKEND}/api/ai-stencil", json=body, timeout=180.0)
    r.raise_for_status()
    b = r.json()["stencil_base64"]
    if "," in b:
        b = b.split(",", 1)[1]
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b))


def mean_abs_diff(path_a: str, path_b: str) -> float:
    """Return mean absolute pixel difference (0..255) between two PNGs.
    Images are resized to the smaller common size and converted to luminance.
    Lower = more consistent between runs.
    """
    a = Image.open(path_a).convert("L")
    b = Image.open(path_b).convert("L")
    w = min(a.size[0], b.size[0])
    h = min(a.size[1], b.size[1])
    a = a.resize((w, h), Image.Resampling.LANCZOS)
    b = b.resize((w, h), Image.Resampling.LANCZOS)
    arr_a = np.asarray(a, dtype=np.int16)
    arr_b = np.asarray(b, dtype=np.int16)
    return float(np.abs(arr_a - arr_b).mean())


async def process_one(client: httpx.AsyncClient, label: str, path: str) -> dict:
    print(f"\n=== {label.upper()} ===")
    with open(path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    paths = {
        "before_a": f"/app/backend/static/prescan_{label}_before_a.png",
        "before_b": f"/app/backend/static/prescan_{label}_before_b.png",
        "after_a":  f"/app/backend/static/prescan_{label}_after_a.png",
        "after_b":  f"/app/backend/static/prescan_{label}_after_b.png",
    }

    t0 = time.time()
    await asyncio.gather(
        gen(client, image_b64, None,             paths["before_a"]),
        gen(client, image_b64, None,             paths["before_b"]),
        gen(client, image_b64, CONSTRAINT_BLOCK, paths["after_a"]),
        gen(client, image_b64, CONSTRAINT_BLOCK, paths["after_b"]),
    )
    print(f"  gen x4: {time.time()-t0:.1f}s")

    variance_before = mean_abs_diff(paths["before_a"], paths["before_b"])
    variance_after  = mean_abs_diff(paths["after_a"],  paths["after_b"])
    print(f"  variance BEFORE (no pre-scan)  : {variance_before:.2f}")
    print(f"  variance AFTER  (with pre-scan): {variance_after:.2f}")
    verdict = "PRE-SCAN REDUCES VARIANCE" if variance_after < variance_before else "PRE-SCAN INCREASES VARIANCE"
    print(f"  verdict: {verdict}")

    return {
        "label": label,
        "variance_before": round(variance_before, 2),
        "variance_after": round(variance_after, 2),
        "verdict": verdict,
    }


async def main():
    async with httpx.AsyncClient() as client:
        results = []
        for label, path in IMAGES.items():
            results.append(await process_one(client, label, path))
    with open("/app/backend/static/prescan_summary.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSummary:")
    for r in results:
        print(f"  {r['label']}: before={r['variance_before']} after={r['variance_after']} → {r['verdict']}")


if __name__ == "__main__":
    asyncio.run(main())
