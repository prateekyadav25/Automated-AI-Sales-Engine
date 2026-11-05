"""Format-specific checks for rendered assets and captions.

A placeholder (a near-uniform image), a fixture asset, a wrong aspect ratio, a
format Instagram rejects, clipped text, or low contrast fails the gate. A
failed gate keeps the creative out of publishing.
"""

from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageStat, UnidentifiedImageError

from app.services.growth.assets import COMMERCIAL_PROVENANCE

IMAGE_MAX_BYTES = 8 * 1024 * 1024
INSTAGRAM_ASPECT = (0.8, 1.91)
CAPTION_LIMITS = {"instagram": 2200, "facebook": 63206}
HASHTAG_LIMITS = {"instagram": 30, "facebook": 30}
TEMPLATE_MARKERS = ("[mock", "not_configured", "{{", "}}", "[insert")
WORD_MARKERS = {
    "lorem ipsum": re.compile(r"\blorem\s+ipsum\b"),
    "todo": re.compile(r"\btodo\b"),
    "xxx": re.compile(r"\bx{3,}\b"),
}
URL_PATTERN = re.compile(r"https?://\S+")
CAROUSEL_RANGE = (2, 10)


def _result(checks: list[dict]) -> dict:
    return {"state": "passed" if checks and all(item["ok"] for item in checks) else "failed", "checks": checks}


def check_image(data: bytes, *, platform: str, expected: tuple[int, int], provenance: str, layout: dict | None, role: str = "feed") -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            fmt = image.format or ""
            mode = image.mode
            size = image.size
            small = image.convert("L").resize((64, 64))
            colors = len(image.convert("RGB").resize((96, 96)).getcolors(96 * 96) or [])
    except (UnidentifiedImageError, OSError, ValueError):
        return _result([{"name": "decode", "ok": False, "detail": "The file is not a readable image."}])
    spread = ImageStat.Stat(small).stddev[0]
    ratio = size[0] / max(size[1], 1)
    check("format", fmt == "JPEG", f"{fmt or 'unknown'}; Instagram accepts JPEG only through the API")
    check("color_mode", mode in {"RGB", "L"}, mode)
    check("dimensions", size == expected, f"{size[0]}x{size[1]} (expected {expected[0]}x{expected[1]})")
    if role == "cover":
        check("aspect_ratio", abs(ratio - 9 / 16) <= 0.01, f"{ratio:.3f} (Reel cover 9:16)")
    elif platform == "instagram":
        check("aspect_ratio", INSTAGRAM_ASPECT[0] <= ratio <= INSTAGRAM_ASPECT[1], f"{ratio:.3f} (Instagram feed 0.8-1.91)")
    check("file_size", len(data) <= IMAGE_MAX_BYTES, f"{len(data)} bytes")
    check("not_placeholder", spread >= 8 and colors >= 24, f"luminance spread {spread:.1f}, {colors} colours")
    check("provenance", provenance in COMMERCIAL_PROVENANCE, provenance)
    if layout is not None:
        check("text_fits", not layout.get("overflow"), "no clipped text" if not layout.get("overflow") else "text was clipped")
        minimum = layout.get("min_contrast")
        check("contrast", minimum is not None and float(minimum) >= 4.5, f"minimum {minimum} (WCAG AA 4.5)")
    return _result(checks)


def caption_problems(text: str) -> list[str]:
    """Template markers count anywhere, links included. Word markers count only as
    whole words in the prose, so a random tracking token or "Mastodon" is not a placeholder."""
    folded = (text or "").casefold()
    prose = URL_PATTERN.sub(" ", folded)
    found = [marker for marker in TEMPLATE_MARKERS if marker in folded]
    return found + [name for name, pattern in WORD_MARKERS.items() if pattern.search(prose)]


def check_caption(caption: str, hashtags: list[str], *, platform: str) -> dict:
    checks: list[dict] = []
    limit = CAPTION_LIMITS.get(platform, 2200)
    full = caption + (" " + " ".join(f"#{tag}" for tag in hashtags) if hashtags else "")
    checks.append({"name": "caption_present", "ok": bool(caption.strip()), "detail": f"{len(caption.strip())} characters"})
    checks.append({"name": "caption_length", "ok": len(full) <= limit, "detail": f"{len(full)} of {limit}"})
    tags = len(hashtags) + len(re.findall(r"(?<!\w)#\w+", caption))
    checks.append({"name": "hashtags", "ok": tags <= HASHTAG_LIMITS.get(platform, 30), "detail": f"{tags} hashtags"})
    markers = caption_problems(full)
    checks.append({"name": "no_placeholders", "ok": not markers, "detail": ", ".join(markers) or "none"})
    return _result(checks)


def check_carousel(slide_reports: list[dict]) -> dict:
    count = len(slide_reports)
    checks = [
        {"name": "slide_count", "ok": CAROUSEL_RANGE[0] <= count <= CAROUSEL_RANGE[1], "detail": f"{count} slides (2-10)"},
        {"name": "slides_passed", "ok": all(report.get("state") == "passed" for report in slide_reports), "detail": f"{sum(1 for report in slide_reports if report.get('state') == 'passed')} of {count} passed"},
    ]
    return _result(checks)
