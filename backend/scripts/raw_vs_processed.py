"""Generate raw-vs-processed pair for skull + lion Heavy — proves post-processing is non-destructive."""
import asyncio, base64, json
import httpx

BACKEND = "http://127.0.0.1:8001"
IMAGES = {
    "skull": "/app/backend/static/portrait3.jpg",
    "lion":  "/app/backend/static/portrait4.jpg",
}


def save_b64(data_url: str, path: str) -> None:
    b = data_url.split(",", 1)[1] if "," in data_url else data_url
    with open(path, "wb") as f:
        f.write(base64.b64decode(b))


async def process(client, label, src):
    with open(src, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    r = await client.post(
        f"{BACKEND}/api/ai-stencil-debug",
        json={"image_base64": image_b64, "regenerate_style": "heavy", "temperature": 0.0},
        timeout=180.0,
    )
    r.raise_for_status()
    d = r.json()
    save_b64(d["raw_base64"], f"/app/backend/static/rawvp_{label}_raw.png")
    save_b64(d["processed_base64"], f"/app/backend/static/rawvp_{label}_processed.png")
    print(f"  {label}: prompt_length={d['prompt_length']} — saved raw + processed")


async def main():
    async with httpx.AsyncClient() as client:
        for label, src in IMAGES.items():
            await process(client, label, src)


if __name__ == "__main__":
    asyncio.run(main())
