"""Screens of the live Mini App, one PNG 1080x1920 per scene.
The Mini App runs in hidden Edge with the app's own signed initData in the URL hash, as Telegram passes it.
Every request that is not a GET is aborted at the browser level: the Mini App can never pay, close or post."""
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

import data
from data import load_settings

VIEW = {"width": 405, "height": 720}  # 9:16; times SCALE gives 1080x1920
SCALE = 1080 / 405
SETTLE = 1200  # ms after a click: sheet slides in, metric lines draw themselves


def mini_url() -> str:
    s = load_settings()
    init = data.init_data(s["bot_token"], int(s["owner_user_id"]), s["first_name"], s["username"], "ru", s["last_name"])
    return s["api_base"].rstrip("/") + "/#tgWebAppData=" + quote(init, safe="") + "&tgWebAppVersion=8.0&tgWebAppPlatform=android"


def get_only(route) -> None:
    if route.request.method != "GET":
        return route.abort()
    route.continue_()


def click(page, locator) -> None:
    locator.first.click()
    page.wait_for_timeout(SETTLE)


def to_top(page) -> None:
    page.evaluate("for (const e of [document.scrollingElement, ...document.querySelectorAll('*')]) if (e.scrollTop) e.scrollTop = 0")
    page.wait_for_timeout(300)


def open_subject(page, facts: dict) -> None:
    if facts["subject"]["source"] == "star":
        click(page, page.get_by_text("Лица знаменитостей"))
        page.locator("input").first.fill(facts["subject"]["name"])
        page.wait_for_timeout(SETTLE)
        click(page, page.get_by_text(facts["subject"]["name"], exact=True))
        page.locator("button.metricLine").first.wait_for(timeout=15000)
    else:  # the home score card opens the latest analysis; only it has photos
        click(page, page.locator("button.homeScoreHero"))
        page.locator("button.shotTile").first.wait_for(timeout=15000)


def harmony_view(page, facts: dict, side: str) -> bool:
    """False when this side has no photo or metrics: the Mini App greys its switch out, so nothing is clicked."""
    if facts["subject"]["source"] == "me":
        click(page, page.locator("button:not(.tab)", has_text=re.compile("^Разбор$")))
    switch = page.locator("button:not(.tab)", has_text=re.compile("^" + ("Анфас" if side == "front" else "Профиль")))
    if switch.first.is_disabled():
        return False
    click(page, switch)
    to_top(page)
    return True


def scene_shot(page, facts: dict, scene: dict, out: Path) -> Path | dict | None:
    kind, ref = scene["kind"], scene.get("ref") or ""
    metric = next((m for m in facts["metrics"] if m["key"] == ref), None)
    if kind == "hook":
        return None  # the hook is voiced over the edit
    if kind == "metric" and metric:
        harmony_view(page, facts, metric["side"])
        name = data.METRICS.get(ref, {}).get("name", [ref])[0]  # the Mini App shows the ru names of markup.ts
        click(page, page.locator("button.metricLine", has_text=re.compile("^" + re.escape(name))))
        page.screenshot(path=out)
        click(page, page.locator("button[aria-label='Закрыть']"))
    elif kind == "outro":  # "see for yourself": the metric lists scroll by, like a screen recording
        return scroll_shot(page, facts, out)
    elif ref in ("harmony_front", "harmony_side", "harmony") or facts["subject"]["source"] == "star":
        if not harmony_view(page, facts, "side" if ref == "harmony_side" else "front"):
            return None  # no profile for this section: the scene is dropped, not shot from the front
        page.screenshot(path=out)
    else:  # overall, rubric sections, verdict of my analysis: the overview tab
        click(page, page.locator("button:not(.tab)", has_text=re.compile("^Обзор$")))
        to_top(page)
        arch = (facts.get("archetype") or {}).get("name")
        if kind == "verdict" and arch and page.get_by_text(arch, exact=True).count():
            page.get_by_text(arch, exact=True).first.evaluate("e => e.scrollIntoView({block: 'center'})")
            page.wait_for_timeout(400)
        page.screenshot(path=out)
    return out


FIXED_BAR = """() => { let e = document.querySelector('button.tab');
  while (e && getComputedStyle(e).position !== 'fixed') e = e.parentElement; return e; }"""


def scroll_shot(page, facts: dict, out: Path) -> dict:
    """Front and profile pages as tall images plus the bottom tab bar on its own: render.py scrolls down the front
    metric list, then the profile one (only if there is one), and keeps the bar in place. y0: where each list starts, output px."""
    talls, y0s = [], []
    for side in ("front", "side"):
        if not harmony_view(page, facts, side):
            continue
        bar = page.evaluate_handle(FIXED_BAR)
        if side == "front":
            top = bar.evaluate("e => e ? e.getBoundingClientRect().top : innerHeight")
            nav = out.with_name(out.stem + "_nav.png")
            page.screenshot(path=nav, clip={"x": 0, "y": top, "width": VIEW["width"], "height": VIEW["height"] - top})
        y0 = page.locator("button.metricLine").first.evaluate("e => e.getBoundingClientRect().top + scrollY")
        bar.evaluate("e => e && (e.style.visibility = 'hidden')")
        talls.append(out.with_name(f"{out.stem}_{side}.png"))
        page.screenshot(path=talls[-1], full_page=True)
        bar.evaluate("e => e && (e.style.visibility = '')")
        y0s.append(max(0, int((y0 - 120) * SCALE)))
    return {"tall": talls, "nav": nav, "y0": y0s}


def shoot(facts: dict, scenes: list[dict], out: Path, cancelled=lambda: False) -> list[Path | None]:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            raise RuntimeError("Не удалось запустить Microsoft Edge для съёмки Mini App")
        try:
            ctx = browser.new_context(viewport=VIEW, device_scale_factor=SCALE, is_mobile=True, has_touch=True, locale="ru-RU")
            ctx.route("**/*", get_only)
            page = ctx.new_page()
            page.goto(mini_url(), wait_until="networkidle")
            open_subject(page, facts)
            shots = []
            for n, scene in enumerate(scenes):
                if cancelled():
                    raise RuntimeError("Отменено")
                if scene["kind"] == "outro" and shots and isinstance(shots[-1], dict):
                    shots.append(shots[-1])  # back-to-back outros share one scroll
                else:
                    shots.append(scene_shot(page, facts, scene, out / f"{n:02}.png"))
            return shots
        finally:
            browser.close()
