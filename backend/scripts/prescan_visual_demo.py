"""Pre-Scan Visual Demo — 3-Layer Architecture (v2, structure-guidance only).

REGRESSION FIX PASS (per user spec):
  - Pre-scan is STRUCTURE GUIDANCE, not image cleaning.
  - No drawing-technique instructions in the preamble. The base prompt already
    owns line weight, density, and hierarchy. Pre-scan never re-specifies them.
  - Layer 3 identifies WHAT structural features must be captured from the
    reference; it never prescribes HOW to render them.
  - Line-hierarchy preservation (strong contours stay strong, mid-detail stays
    readable, fine detail never collapses to noise) is lifted into Layer 1.
  - Enhancement-hints block removed entirely (it was the over-smoothing source).

Layers:
  L1 — Universal Constraints (hard, always applied).
  L2 — Subject-Type Detection: exactly one of
       {portrait, animal, object, landscape, stylized_artwork}.
  L3 — Subject-Specific STRUCTURAL CHECKLIST (features to preserve from the
       reference for the detected category). No drawing-technique language.

Usage:
    python scripts/prescan_visual_demo.py
"""
import asyncio, base64, json, os, re, time
import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

BACKEND = "http://127.0.0.1:8001"

IMAGES = {
    "skull": "/app/backend/static/portrait3.jpg",
    "lion": "/app/backend/static/portrait4.jpg",
}

# ---------------------------------------------------------------------------
# LAYER 1 — Universal Constraints (applies to every image, never overridden).
# Pure structural preservation. No drawing-technique directives.
# ---------------------------------------------------------------------------
LAYER1_UNIVERSAL = [
    "Preserve the EXACT subject count from the reference. Do not duplicate, mirror, pair, tile, or split-panel the subject.",
    "Preserve the EXACT pose, head tilt, and body posture shown in the reference.",
    "Preserve the EXACT orientation and facing direction. Do not rotate or flip.",
    "Preserve the EXACT framing and crop. Do not re-center, zoom, expand, or recompose.",
    "Preserve the EXACT gaze direction of the subject.",
    "Do not reinterpret, replace, or regenerate the subject's identity.",
    # Line-hierarchy preservation — explicit counterweight to previous softening.
    "Preserve the reference's LINE HIERARCHY exactly: strong contours in the reference must remain strong in the stencil, mid-detail must remain readable, fine detail must not collapse into uniform noise.",
    "Do NOT soften, blur, denoise, or normalize edges. Do not reduce edge sharpness below what the reference shows.",
    "Do not change, override, or weaken any line-weight, density, or hierarchy rules specified in the base prompt. This pre-scan adds structural constraints only.",
]

# ---------------------------------------------------------------------------
# LAYER 3 — Subject-Specific STRUCTURAL CHECKLIST.
# Each entry names a feature that must be CAPTURED in its exact reference form.
# No language about line weight, stroke style, density, shading — the base
# prompt already owns those and is the single authority.
# ---------------------------------------------------------------------------
LAYER3_RULES = {
    "portrait": [
        "Capture facial structure, proportions, and expression exactly as shown in the reference.",
        "Capture every facial marking present in the reference (makeup, face paint, scars, tattoos, piercings) in its exact position.",
        "Capture the exact shape and placement of each facial feature (eyes, brows, lips, nose, lashes) without altering proportions.",
    ],
    "animal": [
        "Capture species-specific anatomy exactly (ear shape, muzzle, fangs, horns, mane, fur direction).",
        "Capture head shape and distinguishing features exactly as shown.",
        "Capture the reference's lighting-based coat variation — where the reference shows dense detail, the stencil must too; where it is simpler, keep it simpler.",
    ],
    "object": [
        "Capture geometry, proportions, and symmetry exactly.",
        "Capture every structural edge visible in the reference without distortion.",
    ],
    "landscape": [
        "Capture the reference's spatial layout and depth exactly.",
        "Capture the foreground / midground / background separation without removing compositional elements.",
    ],
    "stylized_artwork": [
        "Capture the graphic shapes and contrast boundaries of the stylization exactly as drawn.",
        "Capture stylized regions (face paint, graphic overlays) in their exact reference positions. Do not normalize, soften, or reinterpret them into a realistic version.",
    ],
}

ALLOWED_CATEGORIES = list(LAYER3_RULES.keys())

CLASSIFY_PROMPT = f"""Classify this tattoo reference image.

Return ONLY JSON in this exact shape:
{{"category": "<one of: {', '.join(ALLOWED_CATEGORIES)}"}}

Rules:
- "category" must be EXACTLY ONE value from the list. Pick the most accurate.
- A human face or person photo is "portrait" (even if stylized with makeup).
- A non-human creature is "animal".
- Pure illustrations, graphic art, or drawings are "stylized_artwork".
- No prose, no markdown, no explanation. JSON only."""


async def classify(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"prescan-{int(time.time()*1000)}",
        system_message="You classify tattoo reference images. Return only JSON matching the schema.",
    ).with_model("gemini", "gemini-2.5-pro")
    msg = UserMessage(text=CLASSIFY_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])
    resp = await chat.send_message(msg)
    m = re.search(r"\{.*\}", resp, re.DOTALL)
    if not m:
        return {"category": None}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"category": None}
    cat = data.get("category") if data.get("category") in ALLOWED_CATEGORIES else None
    return {"category": cat}


def build_preamble(category: str | None) -> str | None:
    """Compose the structural-guidance preamble. Returns None if classification failed."""
    if not category:
        return None

    layer1 = "\n".join(f"- {r}" for r in LAYER1_UNIVERSAL)
    layer3 = "\n".join(f"- {r}" for r in LAYER3_RULES[category])

    return (
        "PRE-SCAN STRUCTURAL DIRECTIVES (image-specific, two layers).\n"
        "Purpose: constrain the structure of the output so the base prompt's line-weight,\n"
        "density, and hierarchy rules are applied to the CORRECT reference features.\n"
        "This block adds constraints ONLY. It does not override, weaken, or replace any\n"
        "drawing-technique rule from the base prompt. If any rule below appears to conflict\n"
        "with the base prompt's line-weight or hierarchy guidance, the base prompt wins.\n\n"
        "LAYER 1 — UNIVERSAL CONSTRAINTS (non-negotiable):\n"
        f"{layer1}\n\n"
        f"LAYER 2 — DETECTED SUBJECT TYPE: {category}\n\n"
        f"LAYER 3 — STRUCTURAL CHECKLIST FOR {category.upper()} "
        "(features to CAPTURE — not how to draw them):\n"
        f"{layer3}"
    )


async def gen_heavy(client: httpx.AsyncClient, image_b64: str, preamble: str | None, out_path: str) -> None:
    body = {
        "image_base64": image_b64,
        "line_color": "black",
        "regenerate_style": "heavy",
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


async def process_one(client: httpx.AsyncClient, label: str, path: str) -> dict:
    print(f"\n=== {label.upper()} ===")
    with open(path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    t0 = time.time()
    classification = await classify(image_b64)
    print(f"  classify: {time.time()-t0:.1f}s  result={classification}")
    preamble = build_preamble(classification.get("category"))
    if preamble:
        print(f"  preamble length: {len(preamble)} chars")
    else:
        print("  preamble: NONE (classification failed — skipping AFTER pass)")

    before_path = f"/app/backend/static/prescan_{label}_before.png"
    after_path = f"/app/backend/static/prescan_{label}_after.png"

    t0 = time.time()
    tasks = [gen_heavy(client, image_b64, None, before_path)]
    if preamble:
        tasks.append(gen_heavy(client, image_b64, preamble, after_path))
    await asyncio.gather(*tasks)
    print(f"  gen: {time.time()-t0:.1f}s")
    print(f"  saved {before_path}")
    if preamble:
        print(f"  saved {after_path}")

    return {"label": label, "classification": classification}


async def main():
    async with httpx.AsyncClient() as client:
        results = []
        for label, path in IMAGES.items():
            results.append(await process_one(client, label, path))
    with open("/app/backend/static/prescan_summary.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
