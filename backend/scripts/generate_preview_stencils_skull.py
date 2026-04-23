"""Generate Low/Medium/Heavy preview stencils against the third reference
(skull-makeup + antlers + dreadlocks — high-contrast stylized photo) that
broke the current prompt.

Output goes to static/ so /api/prompt-preview-skull renders them.
"""
import asyncio
import base64
import os
import sys
import time

import httpx

BACKEND = "http://127.0.0.1:8001"
PORTRAIT = "/app/backend/static/portrait3.jpg"
OUT = {
    "light": "/app/backend/static/stencil_light_skull.png",
    "medium": "/app/backend/static/stencil_medium_skull.png",
    "heavy": "/app/backend/static/stencil_heavy_skull.png",
}


async def gen(client: httpx.AsyncClient, image_b64: str, style: str) -> None:
    print(f"[{style}] requesting…", flush=True)
    t0 = time.time()
    r = await client.post(
        f"{BACKEND}/api/ai-stencil",
        json={
            "image_base64": image_b64,
            "line_color": "black",
            "regenerate_style": style,
        },
        timeout=180.0,
    )
    r.raise_for_status()
    data = r.json()
    stencil_b64 = data["stencil_base64"]
    if "," in stencil_b64:
        stencil_b64 = stencil_b64.split(",", 1)[1]
    with open(OUT[style], "wb") as f:
        f.write(base64.b64decode(stencil_b64))
    print(f"[{style}] saved -> {OUT[style]}  ({time.time()-t0:.1f}s)", flush=True)


async def main() -> None:
    if not os.path.exists(PORTRAIT):
        print(f"Missing reference: {PORTRAIT}", file=sys.stderr)
        sys.exit(1)
    with open(PORTRAIT, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            gen(client, image_b64, "light"),
            gen(client, image_b64, "medium"),
            gen(client, image_b64, "heavy"),
        )
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
