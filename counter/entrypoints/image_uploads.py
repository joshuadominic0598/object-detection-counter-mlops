"""Bound and canonicalize untrusted uploads before any provider sees them."""
from io import BytesIO
import re
import warnings

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 8192
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 128 * 1024
SESSION_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}"


def validate_session(session_id):
    if not re.fullmatch(SESSION_PATTERN, session_id):
        raise HTTPException(400, "Session ID must contain 1–80 letters, numbers, underscores or hyphens.")
    return session_id


def canonical_image(data):
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image exceeds the 10 MB limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG"} or getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(400, "Use a still JPEG or PNG image.")
                width, height = source.size
                if min(width, height) < 32 or max(width, height) > MAX_DIMENSION or width * height > MAX_PIXELS:
                    raise HTTPException(400, "Image must be at least 32×32, at most 8192 px per side and 16 megapixels.")
                source.load()
                clean = ImageOps.exif_transpose(source).convert("RGB")
                result = BytesIO()
                clean.save(result, format="JPEG", quality=92)
                result.seek(0)
                return result, clean.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, "Invalid or unsafe image. Use a still JPEG or PNG.") from None


class RequestSizeLimit:
    """Limit the body before Starlette parses multipart/spools files to disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = MAX_REQUEST_BYTES + 1
        body = bytearray()
        if declared > MAX_REQUEST_BYTES:
            return await JSONResponse({"detail": "Request exceeds the 10 MB image limit."}, 413)(scope, receive, send)
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_REQUEST_BYTES:
                return await JSONResponse({"detail": "Request exceeds the 10 MB image limit."}, 413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)
