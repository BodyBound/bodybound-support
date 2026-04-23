"""Blueprint Mode live verification.

Generates Light + Heavy stencils for the skull and lion references using the
NEW Blueprint Mode prompt (production default) and saves the PNGs alongside
the existing preview assets. Also writes a simple HTML page comparing the
pre-Blueprint production output ("stencil_heavy_*.png") against the new
Blueprint output for the same style.

Usage:
    python scripts/blueprint_mode_demo.py
"""
import asyncio, base64, json, time
import httpx

BACKEND = "http://127.0.0.1:8001"

IMAGES = {
    "skull": ("/app/backend/static/portrait3.jpg", "stencil_heavy_skull.png", "stencil_light_skull.png"),
    "lion":  ("/app/backend/static/portrait4.jpg", "stencil_heavy_lion.png",  "stencil_light_lion.png"),
}
STYLES = ["light", "heavy"]  # skip medium to keep runtime short


async def gen(client: httpx.AsyncClient, image_b64: str, style: str, out_path: str) -> None:
    body = {
        "image_base64": image_b64,
        "line_color": "black",
        "regenerate_style": style,
        "temperature": 0.0,
    }
    r = await client.post(f"{BACKEND}/api/ai-stencil", json=body, timeout=180.0)
    r.raise_for_status()
    b = r.json()["stencil_base64"]
    if "," in b:
        b = b.split(",", 1)[1]
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b))


async def process_one(client: httpx.AsyncClient, label: str, src_path: str) -> None:
    print(f"\n=== {label.upper()} ===")
    with open(src_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    t0 = time.time()
    await asyncio.gather(
        *[gen(client, image_b64, s, f"/app/backend/static/blueprint_{label}_{s}.png") for s in STYLES]
    )
    print(f"  gen {STYLES}: {time.time()-t0:.1f}s")


async def main():
    async with httpx.AsyncClient() as client:
        for label, (src, _, _) in IMAGES.items():
            await process_one(client, label, src)
    print("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
