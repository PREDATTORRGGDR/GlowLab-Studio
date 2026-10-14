import json
import shutil
import sys
from pathlib import Path

import webview

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
UI = Path(getattr(sys, "_MEIPASS", ROOT)) / "ui" / "index.html"
LIB = ROOT / "library"
SETTINGS = ROOT / "settings.json"
SECRETS = ("anthropic_key", "elevenlabs_key", "bot_token")
DEFAULTS = {
    "anthropic_key": "", "claude_model": "claude-sonnet-5-5",
    "elevenlabs_key": "", "voice_id": "", "lang": "ru",
    "api_base": "", "bot_token": "", "owner_user_id": "", "first_name": "", "username": "",
}

for d in ("edits", "fonts", "music", "stars", "analyses"):
    (LIB / d).mkdir(parents=True, exist_ok=True)
(ROOT / "projects").mkdir(exist_ok=True)


def load_settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text("utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def tool(name: str) -> str | None:
    local = ROOT / "bin" / f"{name}.exe"
    return str(local) if local.exists() else shutil.which(name)


class Api:
    def get_settings(self) -> dict:
        # Secrets never reach JS: only the last 4 chars, as a hint that one is saved.
        s = load_settings()
        return {k: (f"••••{v[-4:]}" if v else "") if k in SECRETS else v for k, v in s.items()}

    def save_settings(self, data: dict) -> dict:
        s = load_settings()
        for k in DEFAULTS:
            v = str(data.get(k, "")).strip()
            if k in SECRETS and not v:
                continue  # empty secret field means "keep the saved one"
            s[k] = v
        SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
        return self.get_settings()

    def status(self) -> dict:
        return {"ffmpeg": bool(tool("ffmpeg") and tool("ffprobe"))}


if __name__ == "__main__":
    webview.create_window("GlowLab Studio", str(UI), js_api=Api(), width=1100, height=900, background_color="#0b0b0c")
    webview.start()
