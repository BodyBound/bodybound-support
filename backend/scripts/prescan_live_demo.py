"""Demo: show what the pre-scan classifier returns for each of our test images.
Just the classification step — no generation — so we can see the TAG output
that would drive image-specific rule injection."""
import asyncio, base64, json, os, re, time
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

IMAGES = {
    "portrait (standard)": "/app/backend/static/portrait.jpg",
    "portrait2 (short hair male)": "/app/backend/static/portrait2.jpg",
    "skull makeup woman": "/app/backend/static/portrait3.jpg",
    "roaring lion + thorns": "/app/backend/static/portrait4.jpg",
}

TAG_TO_RULE = {
    "symmetrical": "ONE instance only — no side-by-side duplication.",
    "textured_fur": "Heavy: render FULL mane with many individual flowing strands + dotted light-to-dark contours.",
    "dense_hair_texture": "Heavy: render FULL hair texture with many strands + dotted transitions.",
    "dark_background": "Background must be PURE WHITE regardless of source darkness.",
    "high_contrast": "Dark regions become line work, NEVER solid black fills. No image inversion.",
    "face_paint": "Face paint / makeup patterns must be drawn as outlines — don't replace with clean face.",
    "stylized_artwork": "Preserve pose, framing, gaze direction, every stylistic element exactly.",
    "animal_subject": "Preserve species-correct features (ears, muzzle, fangs, fur direction).",
    "detailed_features": "Capture every visible detail (teeth, scars, wrinkles, accessories).",
    "portrait": "Standard portrait handling — balanced detail distribution.",
    "landscape": "Preserve horizon line and environmental element placement.",
    "object": "Treat as still-life — preserve every contour of the object exactly.",
    "simple_subject": "Do not add complexity that isn't in the source.",
}

CLASSIFY_PROMPT = """Analyze this tattoo reference image. Return a JSON array of lowercase tags from this list (omit any that don't apply):
portrait, animal_subject, stylized_artwork, landscape, object, symmetrical,
face_paint, textured_fur, dense_hair_texture, dark_background, high_contrast,
detailed_features, simple_subject

Return ONLY the JSON array. Example: ["animal_subject","textured_fur"]"""


async def classify_one(name: str, path: str):
    print(f"\n{'─'*72}\n{name}\n{'─'*72}")
    with open(path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"prescan-{int(time.time()*1000)}",
        system_message="You classify tattoo reference images. Return only JSON.",
    ).with_model("gemini", "gemini-2.5-pro")
    msg = UserMessage(
        text=CLASSIFY_PROMPT,
        file_contents=[ImageContent(image_base64=image_b64)],
    )
    t0 = time.time()
    resp = await chat.send_message(msg)
    latency = time.time() - t0
    m = re.search(r"\[[^\]]*\]", resp, re.DOTALL)
    tags = json.loads(m.group(0)) if m else []
    print(f"Latency: {latency:.2f}s")
    print(f"Tags returned: {tags}")
    rules = [TAG_TO_RULE[t] for t in tags if t in TAG_TO_RULE]
    if rules:
        print("Rules that WOULD be injected into prompt:")
        for r in rules:
            print(f"  • {r}")
    else:
        print("No applicable rules (would fall back to base prompt)")


async def main():
    print(f"\n{'='*72}\n  AI PRE-SCAN — LIVE DEMO\n{'='*72}")
    for name, path in IMAGES.items():
        try:
            await classify_one(name, path)
        except Exception as e:
            print(f"[{name}] FAILED: {e}")
    print(f"\n{'='*72}\nDone.\n{'='*72}")


if __name__ == "__main__":
    asyncio.run(main())
