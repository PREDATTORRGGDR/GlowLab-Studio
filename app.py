import ctypes
import json
import os
import shutil
import subprocess
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import httpx
import webview

import data
import miniapp
import render
import script
from data import BUNDLE, DEFAULTS, LIB, PROJECTS, SECRETS, SETTINGS, load_settings, tool

UI = BUNDLE / "ui" / "index.html"


class Media(SimpleHTTPRequestHandler):
    """The page is served over http by pywebview, so it cannot open file://. This serves it photos, edits and
    finished videos: read-only, 127.0.0.1 only, and nothing outside library/ and projects/ (no settings.json)."""
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(data.ROOT), **k)

    def send_head(self):  # both GET and HEAD go through here
        if self.path.lstrip("/").split("/", 1)[0] not in ("library", "projects"):
            return self.send_error(404)
        return super().send_head()

    def log_message(self, *a):
        pass


media = ThreadingHTTPServer(("127.0.0.1", 0), Media)
threading.Thread(target=media.serve_forever, daemon=True).start()


def url(p: Path) -> str:
    return f"http://127.0.0.1:{media.server_port}/" + quote(p.relative_to(data.ROOT).as_posix())


class Api:
    def __init__(self):
        self.job = {"running": False, "step": -1, "detail": "", "error": "", "result": None}
        self.stop = False
        self.last = None  # what the last video was made of: re-render with edited lines reuses its screens

    # ---------- settings ----------
    def get_settings(self) -> dict:
        # Secrets never reach JS: only the last 4 chars, as a hint that one is saved.
        s = load_settings()
        return {k: (f"••••{v[-4:]}" if v else "") if k in SECRETS else v for k, v in s.items()}

    def save_settings(self, form: dict) -> dict:
        s = load_settings()
        for k in DEFAULTS:
            v = str(form.get(k, "")).strip()
            if k in SECRETS and not v:
                continue  # empty secret field means "keep the saved one"
            s[k] = v
        SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
        return self.get_settings()

    def voices(self) -> list[dict]:
        key = load_settings()["elevenlabs_key"]
        if not key:
            return []
        try:
            r = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=20)
            return [{"id": v["voice_id"], "name": v["name"], "free": v.get("category") == "premade"} for v in r.json()["voices"]]
        except Exception:
            return []

    def status(self) -> dict:
        try:
            claude = bool(script.claude_exe())
        except RuntimeError:
            claude = False
        fonts = sorted(p.name for p in (LIB / "fonts").glob("*.ttf"))
        return {"ffmpeg": bool(tool("ffmpeg") and tool("ffprobe")), "claude": claude, "fonts": fonts}

    # ---------- library ----------
    def edits(self) -> list[dict]:
        files = [p for p in (LIB / "edits").iterdir() if p.suffix.lower() in (".mp4", ".mov", ".webm")]
        return [{"name": p.name, "url": url(p)} for p in sorted(files, key=os.path.getmtime, reverse=True)]

    def add_edit(self) -> list[dict]:
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                       file_types=("Видео (*.mp4;*.mov;*.webm)",))
        for p in picked or []:
            shutil.copy2(p, LIB / "edits" / Path(p).name)
        return self.edits()

    def stars(self, q: str = "") -> list[dict]:
        return [{**s, "photo": url(data.STARS / s["slug"] / "front.webp")} for s in data.star_search(q)]

    def my_latest(self, refresh: bool = False) -> dict:
        try:
            if refresh:
                data.refresh_my_analyses()
            items = data.my_analyses()
        except Exception as e:
            return {"error": human(e)}
        if not items:
            return {"error": "Анализов пока нет: нажми «Обновить из GlowLab»"}
        a = items[0]
        photo = data.ANALYSES / str(a["id"]) / "front.jpg"
        return {**a, "photo": url(photo) if photo.exists() else ""}

    # ---------- the video ----------
    def make(self, opts: dict) -> None:
        self._start(self._make, opts)

    def rerender(self, lines: list[dict]) -> None:
        self._start(self._rerender, lines)

    def cancel(self) -> None:
        self.stop = True

    def job_state(self) -> dict:
        return self.job

    def reveal(self, path: str) -> None:
        subprocess.Popen(["explorer", "/select,", str(Path(path))])

    def _start(self, fn, arg) -> None:
        if self.job["running"]:
            return
        self.stop = False
        self.job = {"running": True, "step": 0, "detail": "", "error": "", "result": None}

        def work():
            try:
                fn(arg)
            except Exception as e:
                self.job["error"] = human(e)
                with (PROJECTS / "app.log").open("a", encoding="utf-8") as f:
                    f.write(time.strftime("%d.%m %H:%M ") + traceback.format_exc() + "\n")
            finally:
                self.job["running"] = False

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, step: int, detail: str = "") -> None:
        if self.stop:
            raise RuntimeError("Отменено")
        self.job.update(step=step, detail=detail)

    def _make(self, o: dict) -> None:
        s = load_settings()
        star = o["source"] == "star"
        facts = data.star_facts(o["slug"], s["lang"]) if star else data.my_facts(int(o["analysis_id"]), s["lang"])
        proj = PROJECTS / f"{o['slug'] if star else 'me'}-{time.strftime('%Y%m%d-%H%M%S')}"
        self._progress(0, "Claude пишет текст по цифрам")
        scenes, problems = script.write(facts, s["lang"], s["claude_model"])
        self._progress(1, "Открываю Mini App и снимаю карточки")
        shots = miniapp.shoot(facts, scenes, proj / "shots", lambda: self.stop)
        self.last = {"proj": proj, "scenes": scenes, "shots": shots, "o": o, "problems": problems}
        self._render()

    def _rerender(self, lines: list[dict]) -> None:
        if not self.last:
            raise RuntimeError("Сначала сделай ролик")
        keep = [int(x["i"]) for x in lines]
        text = {int(x["i"]): x["voice"].strip() for x in lines}
        self.last["scenes"] = [{**self.last["scenes"][i], "voice": text[i]} for i in keep]
        self.last["shots"] = [self.last["shots"][i] for i in keep]
        self._render()

    def _render(self) -> None:
        last, o = self.last, self.last["o"]
        self._progress(2, "Голос и склейка")
        edit = LIB / "edits" / o["edit"]
        final = render.make(last["proj"], last["scenes"], last["shots"], edit, float(o.get("start") or 0),
                            float(o.get("length") or 5), o.get("caption", ""), LIB / "fonts" / (o.get("font") or "Oswald.ttf"),
                            lambda d: self._progress(2, d), lambda: self.stop)
        (last["proj"] / "project.json").write_text(json.dumps(
            {"options": o, "scenes": last["scenes"], "shots": [str(p) if p else None for p in last["shots"]]},
            ensure_ascii=False, indent=1), "utf-8")
        self.job["result"] = {"path": str(final), "url": url(final) + f"?v={time.time():.0f}",
                              "seconds": round(render.duration(final), 1), "problems": last["problems"],
                              "scenes": [{"i": i, "kind": x["kind"], "voice": x["voice"]} for i, x in enumerate(last["scenes"])]}


def human(e: Exception) -> str:
    if isinstance(e, RuntimeError):
        return str(e)
    if isinstance(e, httpx.HTTPError):
        return "Нет связи с сервером, проверь интернет и API_BASE"
    return f"Что-то пошло не так: {e}. Подробности в projects\\app.log"


def dark_title(window) -> None:
    """Windows 11: dark title bar in the app's colour instead of the white system one."""
    try:
        hwnd = window.native.Handle.ToInt32()
        for attr, value in ((20, 1), (35, 0x000C0B0B), (36, 0x00F2F2F3)):  # dark mode, caption colour, text colour
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(value)), 4)
    except Exception:
        pass


if __name__ == "__main__":
    w = webview.create_window("GlowLab Studio", str(UI), js_api=Api(), width=1180, height=920, min_size=(900, 700),
                              background_color="#0b0b0c")
    w.events.shown += lambda: dark_title(w)
    webview.start()
