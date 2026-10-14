"""Pillow: one finished 1080x1920 PNG per scene. All text is drawn here, ffmpeg only glues."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app import LIB, ROOT

W, H = 1080, 1920
YEL, WHITE, MUTE = (255, 212, 0), (245, 245, 247), (160, 160, 170)
VERDICT = {"strong": (61, 220, 132), "ok": YEL, "weak": (255, 92, 92)}
LINES = {k: v["lines"] for k, v in json.loads((ROOT / "metrics.json").read_text("utf-8")).items()}
WORDS = {  # ru / en / uk
    "harmony": ("Гармония", "Harmony", "Гармонія"), "dimorphism": ("Диморфизм", "Dimorphism", "Диморфізм"),
    "angularity": ("Угловатость", "Angularity", "Кутастість"), "features": ("Черты", "Features", "Риси"),
    "skin": ("Кожа", "Skin", "Шкіра"), "overall": ("Общий балл", "Overall", "Загальний бал"),
    "front": ("Анфас", "Front", "Анфас"), "side": ("Профиль", "Profile", "Профіль"),
}
DEFAULT_FONT = LIB / "fonts" / "Montserrat.ttf"
ZOOM = 1.45  # face crop: markup points bbox times this


def font(path, size: int, weight: str = "ExtraBold") -> ImageFont.FreeTypeFont:
    path = Path(path) if path and Path(path).exists() else DEFAULT_FONT
    if not path.exists():
        path = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    f = ImageFont.truetype(str(path), size)
    for name in (weight, "Bold"):
        try:
            f.set_variation_by_name(name)
            break
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


def centered(d, y: int, text: str, f, fill, width: int = W - 140, gap: int = 8) -> int:
    for line in wrap(d, text, f, width):
        d.text((W // 2, y), line, font=f, fill=fill, anchor="ma")
        y += f.size + gap
    return y


def fmt(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"


def face(facts: dict, side: str, keys: list[str], box: tuple[int, int, int, int]):
    """Photo fitted into box with markup points; lines of `keys` drawn on top."""
    path = facts["photos"].get(side) or facts["photos"]["front"]
    side = side if facts["photos"].get(side) else "front"
    img = Image.open(path).convert("RGB")
    pts = {k: (x * img.width, y * img.height) for k, (x, y) in (facts["points"].get(side) or {}).items()}
    if pts:  # crop to the face: points bbox * ZOOM, in the box's aspect, kept inside the photo
        xs, ys = [p[0] for p in pts.values()], [p[1] for p in pts.values()]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        cw = max(max(xs) - min(xs), (max(ys) - min(ys)) * box[2] / box[3]) * ZOOM
        cw = min(cw, img.width, img.height * box[2] / box[3])
        ch = cw * box[3] / box[2]
        x0, y0 = min(max(0, cx - cw / 2), img.width - cw), min(max(0, cy - ch / 2), img.height - ch)
        img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
        pts = {k: (x - int(x0), y - int(y0)) for k, (x, y) in pts.items()}
    k = min(box[2] / img.width, box[3] / img.height)
    img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
    pts = {n: (x * k, y * k) for n, (x, y) in pts.items()}
    s = img.width / 1000  # line widths relative to the photo size
    d = ImageDraw.Draw(img, "RGBA")
    r = max(3, 5 * s)
    for x, y in pts.values():
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 150))
    for key in keys:
        for line in LINES.get(key, []):
            xy = [pts[p] for p in line if p in pts]
            if len(xy) > 1:
                d.line(xy, fill=YEL + (255,), width=max(3, int(7 * s)), joint="curve")
            for x, y in xy:
                d.ellipse((x - 2 * r, y - 2 * r, x + 2 * r, y + 2 * r), fill=YEL, outline=(0, 0, 0), width=2)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *img.size), radius=36, fill=255)
    pos = (box[0] + (box[2] - img.width) // 2, box[1] + (box[3] - img.height) // 2)
    return img, pos, mask


def background(path: str) -> Image.Image:
    bg = ImageOps.fit(Image.open(path).convert("RGB"), (W, H)).filter(ImageFilter.GaussianBlur(40))
    return Image.blend(bg, Image.new("RGB", (W, H), (8, 8, 10)), 0.8)


def scale_bar(d, x0: int, y: int, w: int, band: list, value: float, color) -> None:
    b = [v for v in band if v is not None] + [value]
    lo, hi = min(b), max(b)
    span = (hi - lo) or 1
    X = lambda v: x0 + (v - lo) / span * w
    norm = [band[1] if band[1] is not None else band[2], band[4]]
    ideal = [band[2], band[3]]
    d.rounded_rectangle((x0, y, x0 + w, y + 16), radius=8, fill=(45, 45, 52))
    d.rounded_rectangle((X(norm[0]), y, X(norm[1]), y + 16), radius=8, fill=(110, 95, 20))
    d.rounded_rectangle((X(ideal[0]), y, X(ideal[1]), y + 16), radius=8, fill=(61, 220, 132))
    x = X(value)
    d.rounded_rectangle((x - 6, y - 14, x + 6, y + 30), radius=6, fill=color, outline=(0, 0, 0), width=3)


def score_ring(d, cx: int, cy: int, r: int, score: float, f_big, color=YEL) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(55, 55, 62), width=22)
    d.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * max(0, min(score, 10)) / 10, fill=color, width=22)
    d.text((cx, cy), fmt(score), font=f_big, fill=WHITE, anchor="mm")


def frame(facts: dict, scene: dict, out: Path, font_path=None, lang: str = "ru") -> Path:
    i = ("ru", "en", "uk").index(lang) if lang in ("ru", "en", "uk") else 0
    metric = next((m for m in facts["metrics"] if m["key"] == scene.get("ref")), None) if scene["kind"] == "metric" else None
    side = metric["side"] if metric else "front"
    img = background(facts["photos"]["front"])
    d = ImageDraw.Draw(img, "RGBA")

    y = centered(d, 120, scene.get("title", "").upper(), font(font_path, 84), WHITE)
    keys = list(dict.fromkeys(([metric["key"]] if metric else []) + scene.get("highlight", [])))
    small_face = scene["kind"] in ("section", "verdict")
    box = (90, max(y + 40, 330), W - 180, 700 if small_face else 1000)
    photo, pos, mask = face(facts, side, keys, box)
    img.paste(photo, pos, mask)
    d.rounded_rectangle((pos[0], pos[1], pos[0] + photo.width, pos[1] + photo.height), radius=36, outline=YEL + (180,), width=3)
    bottom = pos[1] + photo.height

    if metric:  # plate: name, value, score, scale
        color = VERDICT[metric["verdict"]]
        top = max(bottom + 60, 1420)
        d.rounded_rectangle((60, top, W - 60, top + 400), radius=40, fill=(18, 18, 22, 235), outline=color + (255,), width=4)
        centered(d, top + 40, metric["name"], font(font_path, 52, "Bold"), WHITE, W - 200)
        unit = {"deg": "°", "%": "%", "x": "x"}.get(metric["unit"], "")
        value = f"{metric['value']:.2f}" if metric["unit"] == "x" else f"{metric['value']:.1f}"
        d.text((120, top + 190), value + unit, font=font(font_path, 64, "Bold"), fill=MUTE, anchor="lm")
        d.text((W - 120, top + 190), f"{fmt(metric['score'])} / 10", font=font(font_path, 84), fill=color, anchor="rm")
        if metric.get("band"):
            scale_bar(d, 120, top + 300, W - 240, metric["band"], metric["value"], color)
    elif scene["kind"] in ("section", "verdict"):
        ref = scene.get("ref") or ""
        if scene["kind"] == "verdict":
            score, label = (facts["overall"], WORDS["overall"][i]) if facts["overall"] is not None else (facts["harmony"]["total"], WORDS["harmony"][i])
        else:
            score, label = facts["sections"].get(ref) or facts["harmony"]["total"], WORDS.get(ref, WORDS["harmony"])[i]
        cy = bottom + 330
        score_ring(d, W // 2, cy, 230, score or 0, font(font_path, 150, "Black"))
        y = centered(d, cy + 280, label.upper(), font(font_path, 56, "Bold"), YEL)
        if ref == "harmony" or (scene["kind"] == "verdict" and facts["overall"] is None):
            h = facts["harmony"]
            sub = f"{WORDS['front'][i]} {fmt(h['front'])}   ·   {WORDS['side'][i]} {fmt(h['side'])}"
            centered(d, y + 10, sub, font(font_path, 44, "SemiBold"), WHITE)
        elif scene["kind"] == "verdict" and facts.get("archetype"):
            centered(d, y + 10, facts["archetype"]["name"].upper(), font(font_path, 60), WHITE)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def text_overlay(text: str, out: Path, font_path=None, size: int = 96, pos: str = "bottom") -> Path:
    """Transparent 1080x1920 PNG with the edit's caption, laid over the edit by ffmpeg."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(font_path, size)
    lines = wrap(d, text, f, W - 140)
    block = len(lines) * (size + 12)
    y = {"top": 220, "center": (H - block) // 2}.get(pos, H - 360 - block)
    for line in lines:
        d.text((W // 2, y), line, font=f, fill=WHITE, anchor="ma", stroke_width=max(3, size // 14), stroke_fill=(0, 0, 0))
        y += size + 12
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
