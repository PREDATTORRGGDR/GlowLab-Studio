"""Pillow: the caption over the edit, as a transparent 1080x1920 PNG. Scene frames come from the live Mini App (miniapp.py)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from data import LIB

W, H = 1080, 1920
DEFAULT_FONT = LIB / "fonts" / "Oswald.ttf"  # condensed caps, like the captions in the owner's videos


def font(path, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    path = Path(path) if path and Path(path).exists() else DEFAULT_FONT
    if not path.exists():
        path = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    f = ImageFont.truetype(str(path), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # static font or no such instance
        pass
    return f


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        if cur and d.textlength(f"{cur} {w}", font=f) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur] if cur else lines


def text_overlay(text: str, out: Path, font_path=None, size: int = 96, pos: str = "bottom") -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(font_path, size)
    lines = wrap(d, text, f, W - 140)
    block = len(lines) * (size + 12)
    y = {"top": 220, "center": (H - block) // 2}.get(pos, H - 360 - block)
    for line in lines:
        d.text((W // 2, y), line, font=f, fill=(255, 255, 255), anchor="ma", stroke_width=max(3, size // 14), stroke_fill=(0, 0, 0))
        y += size + 12
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
