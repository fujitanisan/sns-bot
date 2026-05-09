import os
from atproto import Client, client_utils
from atproto import models


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg") -> dict:
    client = Client()
    client.login(
        os.environ["BLUESKY_HANDLE"],
        os.environ["BLUESKY_APP_PASSWORD"],
    )

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
        client.send_post(text=text, embed=embed)
    else:
        client.send_post(text=text)

    return {"platform": "Bluesky", "ok": True}
