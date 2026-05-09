import os
import httpx

BASE = "https://graph.threads.net/v1.0"


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg") -> dict:
    token = os.environ["THREADS_ACCESS_TOKEN"]
    user_id = os.environ["THREADS_USER_ID"]

    if image_data:
        # 画像はURLで渡す必要があるため、別途画像ホスティングが必要
        # ここでは未実装とし、テキストのみ投稿する
        media_type = "TEXT"
        params = {"media_type": media_type, "text": text, "access_token": token}
    else:
        params = {"media_type": "TEXT", "text": text, "access_token": token}

    # ステップ1: コンテナ作成
    r = httpx.post(f"{BASE}/{user_id}/threads", params=params)
    r.raise_for_status()
    container_id = r.json()["id"]

    # ステップ2: 公開
    r2 = httpx.post(
        f"{BASE}/{user_id}/threads_publish",
        params={"creation_id": container_id, "access_token": token},
    )
    r2.raise_for_status()

    return {"platform": "Threads", "ok": True}
