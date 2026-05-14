import os
import asyncio
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


async def broadcast(text: str, image_data: bytes | None = None) -> str:
    enabled = {
        "Bluesky": "BLUESKY_HANDLE" in os.environ and os.environ.get("BLUESKY_HANDLE", ""),
        "X": "X_API_KEY" in os.environ and os.environ.get("X_API_KEY", ""),
        "Threads": "THREADS_ACCESS_TOKEN" in os.environ and os.environ.get("THREADS_ACCESS_TOKEN", ""),
        "Mastodon": "MASTODON_ACCESS_TOKEN" in os.environ and os.environ.get("MASTODON_ACCESS_TOKEN", ""),
    }

    tasks = []
    if enabled["Bluesky"]:
        tasks.append(("Bluesky", asyncio.to_thread(bluesky.post, text, image_data)))
    if enabled["X"]:
        tasks.append(("X", asyncio.to_thread(twitter.post, text, image_data)))
    if enabled["Threads"]:
        tasks.append(("Threads", asyncio.to_thread(threads.post, text, image_data)))
    if enabled["Mastodon"]:
        tasks.append(("Mastodon", asyncio.to_thread(mastodon.post, text, image_data)))

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
        # 60秒待っても画像が来なければテキストだけ投稿
        await asyncio.sleep(60)
        if user_id in pending_captions:
            del pending_captions[user_id]
            result = await broadcast(text)
            await reply(reply_token, f"投稿しました！\n\n{result}")

    async def _run():
        # 前の待機タスクがあればキャンセル
        if user_id in pending_captions:
            pending_captions[user_id]["task"].cancel()

        task = asyncio.create_task(_wait_and_post())
        pending_captions[user_id] = {"text": text, "reply_token": reply_token, "task": task}
        await reply(reply_token, "テキストを受け取りました！\n60秒以内に画像を送ると一緒に投稿します📸\n画像なしでよければそのまま待ってください⏳")

    asyncio.create_task(_run())


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event: MessageEvent):
    message_id = event.message.id
    user_id = event.source.user_id
    reply_token = event.reply_token

    async def _run():
        image_data = await get_image_bytes(message_id)

        # キャプション待機中のテキストがあれば使う
        if user_id in pending_captions:
            caption = pending_captions[user_id]["text"]
            pending_captions[user_id]["task"].cancel()
            del pending_captions[user_id]
        else:
            caption = ""

        result = await broadcast(caption, image_data)
        label = "テキスト＋画像を投稿しました！" if caption else "画像を投稿しました！"
        await reply(reply_token, f"{label}\n\n{result}")

    asyncio.create_task(_run())


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/temp-image/{image_id}")
def temp_image(image_id: str):
    data, mime = image_store.get(image_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=data, media_type=mime)
