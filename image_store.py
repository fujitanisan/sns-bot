"""一時的な画像ストア（Threads API 用に画像URLを提供するため）"""
import time
import uuid

# {id: (data, mime, created_at)}
_store: dict[str, tuple[bytes, str, float]] = {}
TTL_SECONDS = 600  # 10分


def add(data: bytes, mime: str = "image/jpeg") -> str:
    image_id = uuid.uuid4().hex
    _store[image_id] = (data, mime, time.time())
    _cleanup()
    return image_id


def get(image_id: str) -> tuple[bytes, str] | tuple[None, None]:
    _cleanup()
    if image_id in _store:
        data, mime, _ = _store[image_id]
        return data, mime
    return None, None


def _cleanup():
    now = time.time()
    expired = [k for k, (_, _, t) in _store.items() if now - t > TTL_SECONDS]
    for k in expired:
        del _store[k]
