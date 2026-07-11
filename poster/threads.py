import os
import time
import httpx

import image_store

BASE = "https://graph.threads.net/v1.0"


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg", alt: str = "") -> dict:
    token = os.environ["THREADS_ACCESS_TOKEN"]
    user_id = os.environ["THREADS_USER_ID"]

    if image_data:
        # 画像を一時ストアに保存し、Threads が取得できるURLを生成
        image_id = image_store.add(image_data, image_mime)
        base_url = os.environ.get("APP_BASE_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError("APP_BASE_URL 環境変数が未設定です")
        image_url = f"{base_url}/temp-image/{image_id}"

        params = {
            "media_type": "IMAGE",
            "image_url": image_url,
            "text": text,
            "access_token": token,
        }
        if alt:
            params["alt_text"] = alt
    else:
        params = {"media_type": "TEXT", "text": text, "access_token": token}

    # ステップ1: コンテナ作成（Threads が画像URLを取得できず 500 になることがあるのでリトライ）
    last_err = None
    container_id = None
    for attempt in range(4):
        try:
            r = httpx.post(f"{BASE}/{user_id}/threads", params=params, timeout=60)
            r.raise_for_status()
            container_id = r.json()["id"]
            break
        except httpx.HTTPError as e:
            last_err = e
            time.sleep(5)
    if container_id is None:
        raise RuntimeError(f"Threads コンテナ作成失敗: {last_err}")

    # ステップ2: 画像処理の完了を待つ（最大60秒）
    if image_data:
        for _ in range(20):
            status_r = httpx.get(
                f"{BASE}/{container_id}",
                params={"fields": "status", "access_token": token},
                timeout=30,
            )
            status_r.raise_for_status()
            status = status_r.json().get("status")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise RuntimeError("Threads 画像処理エラー")
            time.sleep(3)
        else:
            raise RuntimeError("Threads 画像処理タイムアウト（60秒）")

    # ステップ3: 公開（一時的な失敗に備えてリトライ）
    last_err = None
    for attempt in range(3):
        try:
            r2 = httpx.post(
                f"{BASE}/{user_id}/threads_publish",
                params={"creation_id": container_id, "access_token": token},
                timeout=60,
            )
            r2.raise_for_status()
            break
        except httpx.HTTPError as e:
            last_err = e
            time.sleep(3)
    else:
        raise RuntimeError(f"Threads 公開失敗: {last_err}")

    return {"platform": "Threads", "ok": True}
