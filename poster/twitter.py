import os
import tweepy


def _keys():
    return (
        os.environ["X_API_KEY"].strip(),
        os.environ["X_API_SECRET"].strip(),
        os.environ["X_ACCESS_TOKEN"].strip(),
        os.environ["X_ACCESS_TOKEN_SECRET"].strip(),
    )


def _client_v2():
    key, secret, at, ats = _keys()
    return tweepy.Client(
        consumer_key=key,
        consumer_secret=secret,
        access_token=at,
        access_token_secret=ats,
    )


def _api_v1():
    auth = tweepy.OAuth1UserHandler(*_keys())
    return tweepy.API(auth)


def post(text: str, image_data: bytes | None = None, image_mime: str = "image/jpeg", alt: str = "") -> dict:
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
            if alt:
                api.create_media_metadata(media.media_id, alt)
            client.create_tweet(text=text, media_ids=[media.media_id])
        finally:
            _os.unlink(tmp_path)
    else:
        client.create_tweet(text=text)

    return {"platform": "X", "ok": True}
