import hashlib
import hmac
import json
import subprocess
from urllib.parse import parse_qsl

import app
import data
import miniapp
import render
import script


def test_script_check_catches_invented_numbers():
    f = data.star_facts("drake")
    m = f["metrics"][0]
    good = {"kind": "metric", "ref": m["key"], "title": "x", "voice": f"Плохо: {m['score']:.1f} из 10".replace(".", " и "), "highlight": []}
    bad = {"kind": "section", "ref": "harmony_front", "title": "x", "voice": "Гармония 123,4 из 10", "highlight": ["nope"]}
    assert script.check(f, [good]) == []
    assert script.check(f, [bad]) == ["сцена 1: число 123.4 не из фактов"] and bad["highlight"] == []


def test_hashtags_cleaned_by_code():
    tags, problems = script.clean_tags(["#Drake", "дрейк", "#drake", "#face rate!", "#", "#луксмаксинг"])
    assert tags == ["#drake", "#дрейк", "#facerate", "#луксмаксинг"] and problems == ["хэштегов 4, нужно 8..12"]
    assert script.clean_tags([f"#t{i}" for i in range(15)]) == ([f"#t{i}" for i in range(12)], [])


def test_init_data_passes_server_check():
    # Mirror of api._verify_telegram_init_data in the bot, line for line.
    token = "123456:TEST"
    parsed = dict(parse_qsl(data.init_data(token, 42, "Ника", "nick"), keep_blank_values=True))
    received = parsed.pop("hash")
    check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received)
    assert json.loads(parsed["user"])["id"] == 42


def test_media_server_only_serves_library_and_projects():
    import httpx
    base = f"http://127.0.0.1:{app.media.server_port}"
    assert httpx.get(base + "/settings.json").status_code == 404
    assert httpx.get(base + "/library/../settings.json").status_code == 404
    assert httpx.get(base + "/library/stars/index.json").status_code == 200
    r = httpx.get(base + "/library/stars/index.json", headers={"Range": "bytes=1-4"})  # the edit timeline seeks with Range
    assert r.status_code == 206 and r.content == (data.STARS / "index.json").read_bytes()[1:5]
    assert httpx.get(base + "/settings.json", headers={"Range": "bytes=0-"}).status_code == 404


def test_closed_analysis_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ANALYSES", tmp_path)
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "analysis.json").write_text(json.dumps({"id": 1, "guide_unlocked": False, "metrics": {}}), "utf-8")
    try:
        data.my_facts(1)
        assert False, "closed analysis must not be read"
    except RuntimeError as e:
        assert "Mini App" in str(e)


def test_star_facts_shape():
    f = data.star_facts(data.star_index()[0]["slug"])
    assert f["subject"]["mode"] == "harmony" and f["overall"] is None and f["archetype"] is None
    by_key = {m["key"]: m for m in f["metrics"]}
    for m in f["metrics"]:
        assert m["verdict"] == ("strong" if m["score"] >= 7.5 else "weak" if m["score"] < 5 else "ok")
    assert min(by_key[k]["score"] for k in f["strengths"]) >= max(by_key[k]["score"] for k in f["weaknesses"])


def test_harmony_view_skips_switch_that_is_greyed_out():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.set_content('<meta charset="utf-8"><button>Анфас</button><button disabled>Профиль</button>')
        star = {"subject": {"source": "star"}}
        assert miniapp.harmony_view(page, star, "front") is True
        assert miniapp.harmony_view(page, star, "side") is False  # no profile: no timeout on a disabled click
        browser.close()


def test_outro_scrolls_one_list_when_no_profile(tmp_path):
    from PIL import Image
    tall, nav = tmp_path / "front.png", tmp_path / "nav.png"
    Image.new("RGB", (render.W, 2600), "gray").save(tall)
    Image.new("RGBA", (render.W, 300), "black").save(nav)
    voices = [tmp_path / f"{i}.wav" for i in range(2)]
    for v in voices:
        subprocess.run([render.tool("ffmpeg"), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", v],
                       check=True, capture_output=True)
    out = tmp_path / "outro.mp4"
    render.outro_clip({"tall": [tall], "y0": [100], "nav": nav}, voices, out, tmp_path / "ffmpeg.log")
    assert abs(render.duration(out) - 2 * (1 + render.GAP)) < 0.3  # the one list fills the whole closing lines


def test_settings_keep_secret_and_mask(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(app, "SETTINGS", tmp_path / "settings.json")
    api = app.Api()
    api.save_settings({"bot_token": "123:SECRET9876", "voice_id": "v1"})
    shown = api.save_settings({"bot_token": "", "voice_id": "v2"})  # empty secret keeps the saved one
    assert data.load_settings()["bot_token"] == "123:SECRET9876"
    assert shown["bot_token"] == "••••9876" and shown["voice_id"] == "v2"
