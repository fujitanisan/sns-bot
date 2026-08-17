import os
import asyncio
import datetime
import traceback
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Response
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from linebot.v3.exceptions import InvalidSignatureError

from poster import bluesky, twitter, threads, mastodon
import image_store

app = FastAPI()

configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

# キャプション待機: { user_id: {"text": str, "task": asyncio.Task} }
pending_captions: dict = {}


def extract_alt(text: str) -> tuple[str, str]:
    """テキストから「ALT:」で始まる行を取り出し、(本文, ALTテキスト) を返す"""
    lines = text.splitlines()
    body_lines = []
    alt_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("alt:") or stripped.lower().startswith("alt："):
            alt_lines.append(stripped[4:].strip())
        else:
            body_lines.append(line)
    return "\n".join(body_lines).strip(), " ".join(alt_lines)


async def reply(reply_token: str, text: str):
    async with AsyncApiClient(configuration) as api_client:
        line_api = AsyncMessagingApi(api_client)
        await line_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


async def get_image_bytes(message_id: str) -> bytes:
    async with AsyncApiClient(configuration) as api_client:
        blob_api = AsyncMessagingApiBlob(api_client)
        content = await blob_api.get_message_content(message_id)
        return content


async def broadcast(text: str, image_data: bytes | None = None, alt: str = "") -> str:
    enabled = {
        "Bluesky": "BLUESKY_HANDLE" in os.environ and os.environ.get("BLUESKY_HANDLE", ""),
        "X": "X_API_KEY" in os.environ and os.environ.get("X_API_KEY", ""),
        "Threads": "THREADS_ACCESS_TOKEN" in os.environ and os.environ.get("THREADS_ACCESS_TOKEN", ""),
        "Mastodon": "MASTODON_ACCESS_TOKEN" in os.environ and os.environ.get("MASTODON_ACCESS_TOKEN", ""),
    }

    tasks = []
    if enabled["Bluesky"]:
        tasks.append(("Bluesky", asyncio.to_thread(bluesky.post, text, image_data, "image/jpeg", alt)))
    if enabled["X"]:
        tasks.append(("X", asyncio.to_thread(twitter.post, text, image_data, "image/jpeg", alt)))
    if enabled["Threads"]:
        tasks.append(("Threads", asyncio.to_thread(threads.post, text, image_data, "image/jpeg", alt)))
    if enabled["Mastodon"]:
        tasks.append(("Mastodon", asyncio.to_thread(mastodon.post, text, image_data, "image/jpeg", alt)))

    results = []
    for name, coro in tasks:
        try:
            await coro
            results.append(f"✅ {name}")
        except Exception as e:
            traceback.print_exc()
            results.append(f"❌ {name}: {e}")

    return "\n".join(results) if results else "⚠️ 有効なSNSが設定されていません"


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event: MessageEvent):
    text = event.message.text.strip()
    user_id = event.source.user_id
    reply_token = event.reply_token

    async def _wait_and_post():
        try:
            await asyncio.sleep(60)
            if user_id in pending_captions:
                del pending_captions[user_id]
                body, _ = extract_alt(text)
                result = await broadcast(body)
                print(f"[TEXT] 投稿完了: {result}")
        except Exception as e:
            print(f"[TEXT] エラー: {e}")
            traceback.print_exc()

    async def _run():
        try:
            # 待機中のテキストがあれば、それは画像なし確定なので先に投稿する
            # （破棄すると連投したときに前の投稿が消えてしまう）
            if user_id in pending_captions:
                prev = pending_captions.pop(user_id)
                prev["task"].cancel()
                prev_body, _ = extract_alt(prev["text"])
                if prev_body:
                    result = await broadcast(prev_body)
                    print(f"[TEXT] 前のテキストを投稿: {result}")

            task = asyncio.create_task(_wait_and_post())
            pending_captions[user_id] = {"text": text, "task": task}
            await reply(reply_token, "テキストを受け取りました！\n60秒以内に画像を送ると一緒に投稿します📸\n画像なしでよければそのまま待ってください⏳")
        except Exception as e:
            print(f"[TEXT] _run エラー: {e}")
            traceback.print_exc()

    asyncio.create_task(_run())


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event: MessageEvent):
    message_id = event.message.id
    user_id = event.source.user_id
    reply_token = event.reply_token

    async def _run():
        try:
            image_data = await get_image_bytes(message_id)

            if user_id in pending_captions:
                caption = pending_captions[user_id]["text"]
                pending_captions[user_id]["task"].cancel()
                del pending_captions[user_id]
            else:
                caption = ""

            caption, alt = extract_alt(caption)
            result = await broadcast(caption, image_data, alt)
            label = "テキスト＋画像を投稿しました！" if caption else "画像を投稿しました！"
            await reply(reply_token, f"{label}\n\n{result}")
        except Exception as e:
            print(f"[IMAGE] エラー: {e}")
            traceback.print_exc()
            try:
                await reply(reply_token, f"投稿エラー: {e}")
            except Exception:
                pass

    asyncio.create_task(_run())


@app.get("/")
def health():
    return {"status": "ok"}


# ---- Threads トークン自動更新 ----
# Threads の長期トークンは60日で失効するため、7日ごとに更新APIで延命する。
# 更新後は Render の環境変数にも保存し、再起動時に古いトークンへ巻き戻らないようにする。

TOKEN_REFRESH_DAYS = 7


def _save_env_to_render(env_vars: dict):
    """Render の環境変数を書き換える。トークンを先、日付を後に保存する。"""
    import httpx
    api_key = os.environ.get("RENDER_API_KEY", "").strip()
    service_id = os.environ.get("RENDER_SERVICE_ID", "").strip()
    if not api_key or not service_id:
        print("[TOKEN] RENDER_API_KEY / RENDER_SERVICE_ID が未設定のため保存できません。"
              "再起動のたびに古いトークンへ戻るので、Renderに設定してください")
        return

    for key, value in env_vars.items():
        r = httpx.put(
            f"https://api.render.com/v1/services/{service_id}/env-vars/{key}",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"value": value},
            timeout=30,
        )
        if r.status_code >= 400:
            # 401/403ならAPIキー、404ならサービスIDが怪しい
            raise RuntimeError(f"Render保存失敗 {key}: HTTP {r.status_code} {r.text[:200]}")
        print(f"[TOKEN] Render に {key} を保存しました")


def _maybe_refresh_threads_token():
    import httpx
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        return

    refreshed_at = os.environ.get("THREADS_TOKEN_REFRESHED_AT", "").strip()
    today = datetime.date.today()
    if refreshed_at:
        try:
            last = datetime.date.fromisoformat(refreshed_at)
            days = (today - last).days
            if days < TOKEN_REFRESH_DAYS:
                print(f"[TOKEN] 前回更新から{days}日。{TOKEN_REFRESH_DAYS}日経ったら更新します")
                return
        except ValueError:
            print(f"[TOKEN] THREADS_TOKEN_REFRESHED_AT の形式が不正（{refreshed_at}）。更新を試みます")

    r = httpx.get(
        "https://graph.threads.net/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
        timeout=60,
    )
    if r.status_code >= 400:
        # 発行から24時間以内のトークンは更新できない（Metaの仕様）
        raise RuntimeError(f"Threads更新失敗: HTTP {r.status_code} {r.text[:200]}")
    new_token = r.json()["access_token"]

    os.environ["THREADS_ACCESS_TOKEN"] = new_token
    os.environ["THREADS_TOKEN_REFRESHED_AT"] = today.isoformat()
    print(f"[TOKEN] Threads トークンを更新しました ({today})")
    _save_env_to_render({
        "THREADS_ACCESS_TOKEN": new_token,
        "THREADS_TOKEN_REFRESHED_AT": today.isoformat(),
    })


async def _token_refresh_loop():
    await asyncio.sleep(30)  # 起動直後の混雑を避ける
    while True:
        try:
            await asyncio.to_thread(_maybe_refresh_threads_token)
        except Exception as e:
            print(f"[TOKEN] 更新エラー（次回リトライ）: {e}")
            traceback.print_exc()
        await asyncio.sleep(24 * 3600)  # 1日1回チェック


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_token_refresh_loop())


@app.get("/temp-image/{image_name}")
def temp_image(image_name: str):
    # ".jpg" などの拡張子付きURLにも対応（Threads の画像取得用）
    image_id = image_name.rsplit(".", 1)[0]
    data, mime = image_store.get(image_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=data, media_type=mime)
