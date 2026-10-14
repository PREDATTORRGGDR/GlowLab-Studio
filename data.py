"""Data in: the local star catalog and my analyses from the live GlowLab API (GET only).
Data out: one "facts" dict, the only source of numbers for the script and the frames."""
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app import LIB, ROOT, load_settings

STARS = LIB / "stars"
ANALYSES = LIB / "analyses"
METRICS = json.loads((ROOT / "metrics.json").read_text("utf-8"))
LANGS = ("ru", "en", "uk")
STRONG, WEAK = 7.5, 5.0  # metric verdict: score >= STRONG strong, score < WEAK weak
# miniapp/src/main.tsx `archetypes`, ru / en / uk
ARCHETYPES = {
    "hunter": ("Хищник", "Hunter", "Хижак"), "aristocrat": ("Аристократ", "Aristocrat", "Аристократ"),
    "model": ("Модель", "Model", "Модель"), "brute": ("Силовик", "Brute", "Силовик"),
    "classic": ("Классика", "Classic", "Класика"), "romantic": ("Романтик", "Romantic", "Романтик"),
    "boy_next_door": ("Свой парень", "Boy next door", "Свій хлопець"), "exotic": ("Нестандарт", "Offbeat", "Нестандарт"),
}


# ---------- stars ----------

def star_index() -> list[dict]:
    return json.loads((STARS / "index.json").read_text("utf-8"))


def star_search(q: str = "") -> list[dict]:
    q = q.strip().lower()
    return [s for s in star_index() if q in s["name"].lower()][:40]


def star_facts(slug: str, lang: str = "ru") -> dict:
    s = json.loads((STARS / f"{slug}.json").read_text("utf-8"))
    photos = {side: str(STARS / slug / f"{side}.webp") for side in ("front", "side")}
    subject = {"name": s["name"], "gender": s["gender"], "source": "star", "mode": "harmony"}
    return facts(subject, s["markup"], photos, lang)


# ---------- the one normalizer ----------

def facts(subject: dict, markup: dict, photos: dict, lang: str, extra: dict | None = None) -> dict:
    i = LANGS.index(lang) if lang in LANGS else 0
    metrics = []
    for side in ("front", "side"):
        for key, m in (markup.get(side) or {}).items():
            if not isinstance(m, dict) or m.get("score") is None:
                continue
            sc = m["score"]
            metrics.append({
                "key": key, "name": METRICS.get(key, {}).get("name", [key] * 3)[i], "side": side,
                "value": m.get("value"), "unit": m.get("unit"), "score": sc, "band": m.get("band"),
                "group": m.get("group"), "verdict": "strong" if sc >= STRONG else "weak" if sc < WEAK else "ok",
            })
    ranked = sorted(metrics, key=lambda m: m["score"], reverse=True)
    return {
        "subject": subject,
        "overall": None, "sections": {"harmony": markup.get("harmony")},
        "harmony": {"front": markup.get("harmony_front"), "side": markup.get("harmony_side"), "total": markup.get("harmony")},
        "face_shape": markup.get("face_shape"),
        "archetype": None, "upgrade_paths": [],
        "metrics": metrics,
        "strengths": [m["key"] for m in ranked[:3]],
        "weaknesses": [m["key"] for m in ranked[-3:][::-1]],
        "photos": photos,
        "points": {**(markup.get("points") or {}), "image_size": markup.get("image_size")},
        **(extra or {}),
    }


# ---------- live GlowLab API, GET only ----------

def init_data(bot_token: str, user_id: int, first_name: str = "", username: str = "", lang: str = "ru", last_name: str = "") -> str:
    # Same scheme as the server's api._verify_telegram_init_data: the app signs as a Mini App client.
    # The server overwrites first_name and last_name from here on every request, so they must match Telegram.
    user = {"id": user_id, "first_name": first_name, "last_name": last_name or None, "username": username, "language_code": lang}
    params = {"auth_date": str(int(time.time())), "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False)}
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def get(path: str) -> httpx.Response:
    s = load_settings()
    missing = [n for k, n in (("api_base", "API_BASE"), ("bot_token", "токен бота"), ("owner_user_id", "Telegram id")) if not s[k]]
    if missing:
        raise RuntimeError("Не хватает в настройках: " + ", ".join(missing))
    head = {"X-Telegram-Init-Data": init_data(s["bot_token"], int(s["owner_user_id"]), s["first_name"], s["username"], s["lang"], s["last_name"])}
    if not s["first_name"]:
        raise RuntimeError("Впиши в настройках имя как в Telegram: сервер перезапишет им профиль")
    r = httpx.get(s["api_base"].rstrip("/") + path, headers=head, timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError(f"GlowLab не пустил ({r.status_code}): проверь токен бота и Telegram id")
    r.raise_for_status()
    return r


# ---------- my analyses: cache in library/analyses/<id>/ ----------

def refresh_my_analyses() -> None:
    gender = get("/api/miniapp/me").json().get("analysis_profile")
    for a in get("/api/miniapp/analyses").json()["items"]:
        if a.get("status") != "ready":
            continue
        d = ANALYSES / str(a["id"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "analysis.json").write_text(json.dumps({**a, "_gender": gender}, ensure_ascii=False), "utf-8")
        for url, name in ((a.get("photo_url"), "front.jpg"), (a.get("profile_photo_url"), "profile.jpg")):
            if url and not (d / name).exists():
                (d / name).write_bytes(get(url).content)


def my_analyses() -> list[dict]:
    out = []
    for f in ANALYSES.glob("*/analysis.json"):
        a = json.loads(f.read_text("utf-8"))
        m = a.get("metrics") or {}
        out.append({
            "id": a["id"], "created_at": a["created_at"][:16], "overall": (m.get("gemini") or {}).get("overall_score"),
            "unlocked": bool(a.get("guide_unlocked")), "markup": bool(m.get("markup")), "photo": (f.parent / "front.jpg").exists(),
        })
    return sorted(out, key=lambda a: a["id"], reverse=True)


def my_facts(analysis_id: int, lang: str = "ru") -> dict:
    d = ANALYSES / str(analysis_id)
    a = json.loads((d / "analysis.json").read_text("utf-8"))
    if not a.get("guide_unlocked"):
        raise RuntimeError("Разбор закрыт, открой его в Mini App")
    m = a["metrics"]
    if not m.get("markup"):
        raise RuntimeError("В этом анализе нет разметки лица, выбери анализ посвежее")
    g = m.get("gemini") or {}
    i = LANGS.index(lang) if lang in LANGS else 0
    photos = {side: str(d / name) if (d / name).exists() else None for side, name in (("front", "front.jpg"), ("side", "profile.jpg"))}
    subject = {"name": load_settings()["first_name"], "gender": a.get("_gender"), "source": "me", "mode": "full"}
    arch = g.get("archetype")
    return facts(subject, m["markup"], photos, lang, {
        "overall": g.get("overall_score"),
        "sections": {k: z.get("score") for k, z in (g.get("zones") or {}).items()},
        "archetype": {"name": ARCHETYPES.get(arch, (arch,) * 3)[i], "note": g.get("archetype_note")} if arch else None,
        "upgrade_paths": [p["problem"] for p in g.get("top_upgrade_paths") or [] if p.get("problem")],
    })
