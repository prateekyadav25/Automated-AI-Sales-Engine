"""Optional background imagery from the configured Gemini image model.

Off unless GEMINI_IMAGE_MODEL is set. The result is a background layer for a
branded template. It never carries text claims and is labeled model_generated.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.providers import GEMINI_API_BASE, gemini_model_id


@dataclass(frozen=True)
class ImageResult:
    ok: bool
    data: bytes = b""
    mime: str = ""
    model: str = ""
    reason: str = ""


def generate_background(client: Any, *, api_key: str, model: str, prompt: str) -> ImageResult:
    if not api_key or not model:
        return ImageResult(ok=False, reason="NOT_CONFIGURED. Set GEMINI_API_KEY and GEMINI_IMAGE_MODEL.")
    model_id = gemini_model_id(model)
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    try:
        response = client.post(
            f"{GEMINI_API_BASE}/models/{model_id}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body,
        )
    except (httpx.HTTPError, TimeoutError) as exc:
        return ImageResult(ok=False, model=model_id, reason=f"Image model request failed ({exc.__class__.__name__}).")
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 429:
        return ImageResult(ok=False, model=model_id, reason="Image model quota is used up.")
    if status_code >= 400:
        return ImageResult(ok=False, model=model_id, reason=f"Image model refused the request ({status_code}).")
    try:
        payload = response.json() or {}
    except (ValueError, TypeError):
        return ImageResult(ok=False, model=model_id, reason="Image model response was not JSON.")
    for candidate in payload.get("candidates") or []:
        for part in ((candidate or {}).get("content") or {}).get("parts") or []:
            inline = (part or {}).get("inlineData") or (part or {}).get("inline_data")
            if not isinstance(inline, dict) or not inline.get("data"):
                continue
            try:
                data = base64.b64decode(str(inline["data"]), validate=False)
            except ValueError:
                continue
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
            return ImageResult(ok=True, data=data, mime=mime, model=str(payload.get("modelVersion") or model_id))
    return ImageResult(ok=False, model=model_id, reason="The image model returned no image.")
