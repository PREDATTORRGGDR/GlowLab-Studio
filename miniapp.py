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


def harmony_view(page, facts: dict, side: str) -> None:
    if facts["subject"]["source"] == "me":
        click(page, page.locator("button:not(.tab)", has_text=re.compile("^Разбор$")))
    click(page, page.locator("button:not(.tab)", has_text=re.compile("^" + ("Анфас" if side == "front" else "Профиль"))))
    to_top(page)


def scene_shot(page, facts: dict, scene: dict, out: Path) -> Path | None:
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
    elif ref in ("harmony_front", "harmony_side", "harmony") or kind == "outro" or facts["subject"]["source"] == "star":
        harmony_view(page, facts, "side" if ref == "harmony_side" else "front")
        if kind == "outro":  # "see for yourself": the metric list
            page.locator("button.metricLine").first.evaluate("e => e.scrollIntoView({block: 'start'})")
            page.wait_for_timeout(400)
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
                shots.append(scene_shot(page, facts, scene, out / f"{n:02}.png"))
            return shots
        finally:
            browser.close()
