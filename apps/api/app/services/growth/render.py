"""Branded templates rendered with Pillow.

A card uses the tenant's palette and logo, real TrueType fonts, and text
measured against the background so contrast and overflow are reported, not
assumed. Without a usable font the renderer reports NOT_CONFIGURED instead of
falling back to a bitmap placeholder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat, UnidentifiedImageError

from app.core.config import get_settings

SIZES = {"portrait": (1080, 1350), "square": (1080, 1080), "landscape": (1200, 630), "vertical": (1080, 1920)}
FALLBACK_PALETTE = ["#1f3a5f", "#3d6ea8", "#f2b544"]
_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


class RenderUnavailable(RuntimeError):
    """The renderer cannot produce commercial output in this environment."""


@dataclass
class BrandKit:
    name: str
    colors: list[str]
    regular_font: str
    bold_font: str
    logo: Image.Image | None = None
    handle: str = ""
    notes: list[str] = field(default_factory=list)


def resolve_fonts() -> tuple[str, str]:
    settings = get_settings()
    regular = next((path for path in (settings.creative_font_path, *_REGULAR) if path and os.path.isfile(path)), "")
    bold = next((path for path in (settings.creative_font_bold_path, *_BOLD) if path and os.path.isfile(path)), "")
    if not regular:
        raise RenderUnavailable("NOT_CONFIGURED. No TrueType font was found. Set CREATIVE_FONT_PATH or install fonts-dejavu-core.")
    return regular, bold or regular


def hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def luminance(rgb: tuple[float, ...]) -> float:
    def channel(value: float) -> float:
        scaled = value / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(part) for part in rgb[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    high, low = sorted((luminance(left), luminance(right)), reverse=True)
    return round((high + 0.05) / (low + 0.05), 2)


def load_logo(data: bytes) -> Image.Image | None:
    try:
        with Image.open(BytesIO(data)) as raw:
            return raw.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _gradient(size: tuple[int, int], start: str, end: str) -> Image.Image:
    vertical = Image.linear_gradient("L").resize(size)
    horizontal = Image.linear_gradient("L").transpose(Image.Transpose.ROTATE_90).transpose(Image.Transpose.FLIP_LEFT_RIGHT).resize(size)
    mask = ImageChops.add(vertical, horizontal, scale=2.0)
    first = Image.new("RGB", size, hex_rgb(start))
    second = Image.new("RGB", size, hex_rgb(end))
    return Image.composite(second, first, mask)


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
            current = word
            while draw.textlength(current, font=font) > width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and draw.textlength(current[:cut] + "-", font=font) > width:
                    cut -= 1
                lines.append(current[:cut] + "-")
                current = current[cut:]
        if current:
            lines.append(current)
    return lines


def _fit(draw: ImageDraw.ImageDraw, text: str, path: str, width: int, max_lines: int, sizes: range) -> tuple[ImageFont.FreeTypeFont, list[str], bool]:
    font = ImageFont.truetype(path, sizes.start)
    lines = _wrap(draw, text, font, width)
    for size in sizes:
        font = ImageFont.truetype(path, size)
        lines = _wrap(draw, text, font, width)
        if len(lines) <= max_lines:
            return font, lines, False
    return font, lines[:max_lines], True


def _text_block(draw: ImageDraw.ImageDraw, image: Image.Image, lines: list[str], font: ImageFont.FreeTypeFont, x: int, y: int, fill: tuple[int, int, int], spacing: float) -> tuple[int, float]:
    ascent, descent = font.getmetrics()
    step = int((ascent + descent) * spacing)
    lowest = 99.0
    for line in lines:
        box = draw.textbbox((x, y), line, font=font)
        if box[2] > box[0] and box[3] > box[1]:
            region = image.crop((max(box[0], 0), max(box[1], 0), min(box[2], image.width), min(box[3], image.height)))
            mean = tuple(ImageStat.Stat(region.convert("RGB")).mean)
            lowest = min(lowest, contrast(fill, mean))
        draw.text((x, y), line, font=font, fill=fill)
        y += step
    return y, (lowest if lowest != 99.0 else 21.0)


def _logo_chip(canvas: Image.Image, logo: Image.Image, x: int, y: int, height: int) -> int:
    scale = height / max(logo.height, 1)
    width = max(1, int(logo.width * scale))
    if width > canvas.width // 3:
        width = canvas.width // 3
        height = max(1, int(logo.height * width / max(logo.width, 1)))
    resized = logo.resize((width, height), Image.Resampling.LANCZOS)
    pad = max(10, height // 5)
    chip = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle((0, 0, chip.width - 1, chip.height - 1), radius=pad, fill=(255, 255, 255, 240))
    chip.alpha_composite(resized, (pad, pad))
    canvas.alpha_composite(chip, (x, y))
    return chip.height


def render_card(
    kit: BrandKit,
    size_name: str,
    *,
    eyebrow: str,
    headline: str,
    body: str,
    footer: str,
    cta: str = "",
    counter: str = "",
    background: Image.Image | None = None,
) -> tuple[Image.Image, dict]:
    size = SIZES[size_name]
    width, height = size
    colors = (kit.colors + FALLBACK_PALETTE)[:3]
    base = _cover(background, size) if background is not None else _gradient(size, colors[0], colors[1] if len(colors) > 1 else colors[0])
    canvas = base.convert("RGBA")
    shade = Image.new("RGBA", size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    radius = int(min(size) * 0.42)
    accent = hex_rgb(colors[2] if len(colors) > 2 else colors[0])
    shade_draw.ellipse((width - radius, height - radius, width + radius, height + radius), fill=(*accent, 60))
    canvas.alpha_composite(shade)
    mean = tuple(ImageStat.Stat(canvas.convert("RGB")).mean)
    white, ink = (255, 255, 255), (17, 24, 39)
    text_color = white if contrast(white, mean) >= contrast(ink, mean) else ink
    overlay_applied = False
    if background is not None or contrast(text_color, mean) < 4.5:
        tint = (0, 0, 0, 120) if text_color == white else (255, 255, 255, 140)
        canvas.alpha_composite(Image.new("RGBA", size, tint))
        overlay_applied = True
    draw = ImageDraw.Draw(canvas)
    margin = int(width * 0.08)
    inner = width - margin * 2
    y = margin
    logo_drawn = False
    if kit.logo is not None:
        y += _logo_chip(canvas, kit.logo, margin, y, int(height * 0.055)) + int(height * 0.035)
        logo_drawn = True
        draw = ImageDraw.Draw(canvas)
    small = ImageFont.truetype(kit.regular_font, max(22, width // 36))
    if size_name == "vertical":
        y = max(y, int(height * 0.27))
    if counter:
        draw.text((width - margin - draw.textlength(counter, font=small), margin), counter, font=small, fill=text_color)
    contrasts: list[float] = []
    if eyebrow:
        eyebrow_font = ImageFont.truetype(kit.bold_font, max(24, width // 34))
        y, value = _text_block(draw, canvas, [eyebrow.upper()[:48]], eyebrow_font, margin, y, text_color, 1.3)
        contrasts.append(value)
        draw.rectangle((margin, y + 4, margin + width // 9, y + 10), fill=accent)
        y += int(height * 0.03)
    footer_reserve = int(height * 0.2)
    headline_font, headline_lines, headline_overflow = _fit(draw, headline, kit.bold_font, inner, 5, range(max(44, width // 11), 35, -4))
    y, value = _text_block(draw, canvas, headline_lines, headline_font, margin, y, text_color, 1.15)
    contrasts.append(value)
    body_overflow = False
    body_size = 0
    if body:
        y += int(height * 0.025)
        room = max(1, (height - footer_reserve - y) // max(1, int(max(26, width // 28) * 1.45)))
        body_font, body_lines, body_overflow = _fit(draw, body, kit.regular_font, inner, min(7, room), range(max(28, width // 28), 23, -2))
        body_size = body_font.size
        y, value = _text_block(draw, canvas, body_lines, body_font, margin, y, text_color, 1.4)
        contrasts.append(value)
    footer_y = height - margin - int(height * 0.05)
    if cta:
        cta_font = ImageFont.truetype(kit.bold_font, max(26, width // 32))
        pill_w = int(min(inner, draw.textlength(cta, font=cta_font) + margin))
        pill_h = int(cta_font.size * 2.0)
        top = footer_y - pill_h - int(height * 0.02)
        pill_text = white if contrast(white, accent) >= contrast(ink, accent) else ink
        draw.rounded_rectangle((margin, top, margin + pill_w, top + pill_h), radius=pill_h // 2, fill=accent)
        draw.text((margin + (pill_w - draw.textlength(cta, font=cta_font)) / 2, top + pill_h / 2), cta, font=cta_font, fill=pill_text, anchor="lm")
        contrasts.append(contrast(pill_text, accent))
        if top < y:
            body_overflow = True
    if footer:
        _y, value = _text_block(draw, canvas, [footer[:70]], small, margin, footer_y, text_color, 1.2)
        contrasts.append(value)
    report = {
        "size": [width, height],
        "headline_font_px": headline_font.size,
        "headline_lines": len(headline_lines),
        "body_font_px": body_size,
        "overflow": headline_overflow or body_overflow,
        "min_contrast": min(contrasts) if contrasts else None,
        "text_color": "#%02x%02x%02x" % text_color,
        "overlay": overlay_applied,
        "logo": logo_drawn,
        "palette": colors,
        "brand_palette": bool(kit.colors),
        "fonts": [os.path.basename(kit.regular_font), os.path.basename(kit.bold_font)],
    }
    return canvas.convert("RGB"), report


def jpeg_bytes(image: Image.Image, quality: int = 90) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True, subsampling=0 if quality >= 95 else 2)
    return buffer.getvalue()


def png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
