import os
import tweepy


def _client_v2():
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def _api_v1():
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return tweepy.API(auth)


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg") -> dict:
    client = _client_v2()

    if image_data:
        # 画像アップロードはv1 APIが必要
        api = _api_v1()
        import tempfile, os as _os
        suffix = ".jpg" if "jpeg" in image_mime else ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(image_data)
            tmp_path = f.name
        try:
            media = api.media_upload(tmp_path)
            client.create_tweet(text=text, media_ids=[media.media_id])
        finally:
            _os.unlink(tmp_path)
    else:
        client.create_tweet(text=text)

    return {"platform": "X", "ok": True}
