import os
import re
from atproto import Client, client_utils
from atproto import models


def _build_text(text: str) -> client_utils.TextBuilder:
    builder = client_utils.TextBuilder()
    url_pattern = re.compile(r'https?://\S+')
    last = 0
    for m in url_pattern.finditer(text):
        if m.start() > last:
            builder.text(text[last:m.start()])
        builder.link(m.group(), m.group())
        last = m.end()
    if last < len(text):
        builder.text(text[last:])
    return builder


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg") -> dict:
    client = Client()
    client.login(
        os.environ["BLUESKY_HANDLE"],
        os.environ["BLUESKY_APP_PASSWORD"],
    )

    rich_text = _build_text(text)

    if image_data:
        upload = client.upload_blob(image_data)
        embed = models.AppBskyEmbedImages.Main(
            images=[
                models.AppBskyEmbedImages.Image(
                    alt="",
                    image=upload.blob,
                )
            ]
        )
        client.send_post(text=rich_text, embed=embed)
    else:
        client.send_post(text=rich_text)

    return {"platform": "Bluesky", "ok": True}
