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

    # ステップ1: コンテナ作成
    r = httpx.post(f"{BASE}/{user_id}/threads", params=params)
    r.raise_for_status()
    container_id = r.json()["id"]

    # ステップ2: 画像処理の完了を待つ（最大30秒）
    if image_data:
        for _ in range(15):
            status_r = httpx.get(
                f"{BASE}/{container_id}",
                params={"fields": "status", "access_token": token},
            )
            status_r.raise_for_status()
            status = status_r.json().get("status")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise RuntimeError("Threads 画像処理エラー")
            time.sleep(2)
        else:
            raise RuntimeError("Threads 画像処理タイムアウト（30秒）")

    # ステップ3: 公開
    r2 = httpx.post(
        f"{BASE}/{user_id}/threads_publish",
        params={"creation_id": container_id, "access_token": token},
    )
    r2.raise_for_status()

    return {"platform": "Threads", "ok": True}
