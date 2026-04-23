"""One-off demo: simulate the AI Pre-Scan feature against the lion image.
  1. Call Gemini in text-only mode to classify the reference
  2. Map tags -> injected rules
  3. Print both the tags and the rules preamble
  4. Generate Heavy WITH and WITHOUT the preamble for direct comparison
"""
import asyncio, base64, json, os, re, time
import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

BACKEND = "http://127.0.0.1:8001"
PORTRAIT = "/app/backend/static/portrait4.jpg"

TAG_TO_RULE = {
    "symmetrical": "IMPORTANT: This subject has natural symmetry (eg front-facing face/animal). Render exactly ONE instance filling the frame as in the source. Do NOT duplicate the subject side-by-side.",
    "textured_fur": "IMPORTANT: For Heavy detail render the FULL mane/fur with many individual flowing strands — dozens of hair lines across the subject — plus dotted light-to-dark contour guides wherever light hits differently. Do not under-shade.",
    "dense_hair_texture": "IMPORTANT: For Heavy detail render the FULL hair with many flowing strands plus dotted light-to-dark contour guides.",
    "dark_background": "IMPORTANT: The background of the stencil is PURE WHITE regardless of how dark the source photo is. Do not reproduce the dark background as black.",
    "high_contrast": "IMPORTANT: Dark regions in the source must be drawn as line work only — never as solid black fills. Do not invert the image.",
    "face_paint": "IMPORTANT: Face paint / makeup / skull paint patterns must be drawn as outlines on the face — do not replace with a clean un-painted face.",
    "stylized_artwork": "IMPORTANT: Preserve the exact pose, framing, gaze direction and every stylistic element visible in the source. Do not reinterpret.",
    "animal_subject": "IMPORTANT: Subject is an animal. Preserve species-correct features (ears, muzzle, fangs, fur direction) exactly as shown.",
    "detailed_features": "IMPORTANT: Capture every visible detail (teeth, scars, wrinkles, small accessories) — these are features the user chose the reference for.",
}

CLASSIFY_PROMPT = """You are analyzing a tattoo reference image. Return a JSON array of short lowercase tags drawn ONLY from this list (omit any that don't apply):
- portrait
- animal_subject
- stylized_artwork
- landscape
- object
- symmetrical
- face_paint
- textured_fur
- dense_hair_texture
- dark_background
- high_contrast
- detailed_features
- simple_subject

Return ONLY the JSON array. Example: ["animal_subject","textured_fur","dark_background"]"""


async def classify(image_b64: str) -> list[str]:
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"prescan-demo-{int(time.time())}",
        system_message="You classify images into a fixed tag set. Return only JSON.",
    ).with_model("gemini", "gemini-2.5-pro")
    msg = UserMessage(
        text=CLASSIFY_PROMPT,
        file_contents=[ImageContent(image_base64=image_b64)],
    )
    resp = await chat.send_message(msg)
    m = re.search(r"\[.*?\]", resp, re.DOTALL)
    return json.loads(m.group(0)) if m else []


def build_preamble(tags: list[str]) -> str:
    rules = [TAG_TO_RULE[t] for t in tags if t in TAG_TO_RULE]
    if not rules:
        return ""
    return "\n\nIMAGE-SPECIFIC RULES (derived from automatic pre-scan of this reference — apply these on top of all other rules):\n" + "\n".join(f"- {r}" for r in rules) + "\n"


async def gen_heavy(client: httpx.AsyncClient, image_b64: str, preamble_injection: str, label: str) -> str:
    """Call ai-stencil with a custom preamble injected into the prompt (via a field backend will respect).
    For this demo we use the regenerate flow and append the preamble to shading_detail description.
    """
    body = {
        "image_base64": image_b64,
        "line_color": "black",
        "regenerate_style": "heavy",
    }
    if preamble_injection:
        body["style"] = preamble_injection
    r = await client.post(f"{BACKEND}/api/ai-stencil", json=body, timeout=180.0)
    r.raise_for_status()
    b = r.json()["stencil_base64"]
    if "," in b: b = b.split(",", 1)[1]
    out_path = f"/app/backend/static/prescan_demo_{label}.png"
    with open(out_path, "wb") as f: f.write(base64.b64decode(b))
    return out_path


async def main():
    print(f"\n{'=' * 72}\n  AI PRE-SCAN DEMO — lion reference\n{'=' * 72}\n")
    with open(PORTRAIT, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    print("STEP 1 — Classify image via Gemini (text+image)…")
    t0 = time.time()
    tags = await classify(image_b64)
    print(f"  Classification latency: {time.time()-t0:.2f}s")
    print(f"  Tags returned: {tags}\n")

    print("STEP 2 — Build image-specific rules preamble:")
    preamble = build_preamble(tags)
    print(preamble if preamble else "  (no applicable rules)\n")

    print("STEP 3 — Generate Heavy WITHOUT preamble (current production behavior)…")
    async with httpx.AsyncClient() as c:
        t0 = time.time()
        p_before = await gen_heavy(c, image_b64, "", "before")
        print(f"  Saved: {p_before}  ({time.time()-t0:.1f}s)")
        t0 = time.time()
        p_after = await gen_heavy(c, image_b64, preamble, "after")
        print(f"  Saved: {p_after}  ({time.time()-t0:.1f}s)")

    print("\nDone. Preview URL: https://stencil-ai-fallback.preview.emergentagent.com/api/prompt-preview-prescan-demo")


if __name__ == "__main__":
    asyncio.run(main())
