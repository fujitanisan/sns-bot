import os
import httpx


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg") -> dict:
    token = os.environ["MASTODON_ACCESS_TOKEN"]
    instance = os.environ.get("MASTODON_INSTANCE_URL", "https://mastodon.social").rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}

    media_ids = []
    if image_data:
        # メディアアップロード
        files = {"file": ("image.jpg", image_data, image_mime)}
        r = httpx.post(
            f"{instance}/api/v2/media",
            headers=headers,
            files=files,
            timeout=30,
        )
        r.raise_for_status()
        media_ids.append(r.json()["id"])

    # ステータス投稿
    data = {"status": text}
    if media_ids:
        data["media_ids[]"] = media_ids

    r2 = httpx.post(
        f"{instance}/api/v1/statuses",
        headers=headers,
        data=data,
        timeout=30,
    )
    r2.raise_for_status()

    return {"platform": "Mastodon", "ok": True}
