"""Side-by-side demo: for skull + lion references, generate Heavy BEFORE
(no pre-scan) and AFTER (classification → rule injection via extra_preamble)."""
import asyncio, base64, json, os, re, time
import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

BACKEND = "http://127.0.0.1:8001"

IMAGES = {
    "skull": "/app/backend/static/portrait3.jpg",
    "lion": "/app/backend/static/portrait4.jpg",
}

TAG_TO_RULE = {
    "symmetrical": "ONE instance only — no side-by-side duplication of the subject.",
    "textured_fur": "Heavy detail: render FULL mane/fur with many individual flowing strands (dozens of visible hairs) and dotted light-to-dark contour guides across the coat.",
    "dense_hair_texture": "Heavy detail: render FULL hair with many flowing strands and dotted light-to-dark transition guides.",
    "dark_background": "The stencil background must be PURE WHITE regardless of how dark the reference photo is.",
    "high_contrast": "Dark regions must be drawn as line work only — NEVER as solid black fills. Do not invert the image.",
    "face_paint": "Face paint / makeup / skull-paint patterns must be drawn as outlines on the skin — do NOT replace with a clean un-painted face.",
    "stylized_artwork": "Preserve the exact pose, framing, gaze direction, and every stylistic element visible in the source. Do not reinterpret.",
    "animal_subject": "Subject is an animal. Preserve species-correct features (ears, muzzle, fangs, fur direction) exactly as shown.",
    "detailed_features": "Capture every visible detail in the reference (teeth, scars, wrinkles, small accessories, texture).",
}

CLASSIFY_PROMPT = """Analyze this tattoo reference image. Return a JSON array of lowercase tags from this list (omit any that don't apply):
portrait, animal_subject, stylized_artwork, landscape, object, symmetrical,
face_paint, textured_fur, dense_hair_texture, dark_background, high_contrast,
detailed_features, simple_subject

Return ONLY the JSON array."""


async def classify(image_b64: str) -> list[str]:
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"prescan-{int(time.time()*1000)}",
        system_message="You classify tattoo reference images. Return only JSON.",
    ).with_model("gemini", "gemini-2.5-pro")
    msg = UserMessage(text=CLASSIFY_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])
    resp = await chat.send_message(msg)
    m = re.search(r"\[[^\]]*\]", resp, re.DOTALL)
    return json.loads(m.group(0)) if m else []


def build_preamble(tags: list[str]) -> str:
    rules = [TAG_TO_RULE[t] for t in tags if t in TAG_TO_RULE]
    if not rules:
        return ""
    return ("IMAGE-SPECIFIC RULES (derived from automatic pre-scan of THIS "
            "reference image — these take priority over the generic rules below):\n"
            + "\n".join(f"- {r}" for r in rules))


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
    if "," in b: b = b.split(",", 1)[1]
    with open(out_path, "wb") as f: f.write(base64.b64decode(b))


async def process_one(client, label: str, path: str) -> None:
    print(f"\n=== {label.upper()} ===")
    with open(path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    t0 = time.time()
    tags = await classify(image_b64)
    print(f"  classify: {time.time()-t0:.1f}s  tags={tags}")
    preamble = build_preamble(tags)
    print(f"  preamble length: {len(preamble)} chars")

    # Generate both in parallel
    before_path = f"/app/backend/static/prescan_{label}_before.png"
    after_path = f"/app/backend/static/prescan_{label}_after.png"
    t0 = time.time()
    await asyncio.gather(
        gen_heavy(client, image_b64, None, before_path),
        gen_heavy(client, image_b64, preamble, after_path),
    )
    print(f"  both heavies: {time.time()-t0:.1f}s")
    print(f"  saved {before_path}")
    print(f"  saved {after_path}")


async def main():
    async with httpx.AsyncClient() as client:
        for label, path in IMAGES.items():
            await process_one(client, label, path)
    print("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
