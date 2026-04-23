"""Fourth preview — lion with thorn crown, textured mane, fangs.
Stress-tests hair/fur texture density + animal subject."""
import asyncio, base64, os, sys, time
import httpx

BACKEND = "http://127.0.0.1:8001"
PORTRAIT = "/app/backend/static/portrait4.jpg"
OUT = {
    "light": "/app/backend/static/stencil_light_lion.png",
    "medium": "/app/backend/static/stencil_medium_lion.png",
    "heavy": "/app/backend/static/stencil_heavy_lion.png",
}


async def gen(client, image_b64, style):
    print(f"[{style}] requesting…", flush=True)
    t0 = time.time()
    r = await client.post(f"{BACKEND}/api/ai-stencil",
        json={"image_base64": image_b64, "line_color": "black", "regenerate_style": style},
        timeout=180.0)
    r.raise_for_status()
    d = r.json()
    b = d["stencil_base64"]
    if "," in b: b = b.split(",", 1)[1]
    with open(OUT[style], "wb") as f: f.write(base64.b64decode(b))
    print(f"[{style}] saved ({time.time()-t0:.1f}s)", flush=True)


async def main():
    with open(PORTRAIT, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    async with httpx.AsyncClient() as c:
        await asyncio.gather(gen(c, b64, "light"), gen(c, b64, "medium"), gen(c, b64, "heavy"))

asyncio.run(main())
