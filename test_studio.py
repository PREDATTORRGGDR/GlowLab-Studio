import hashlib
import hmac
import json
from urllib.parse import parse_qsl

import app
import data


def test_init_data_passes_server_check():
    # Mirror of api._verify_telegram_init_data in the bot, line for line.
    token = "123456:TEST"
    parsed = dict(parse_qsl(data.init_data(token, 42, "Ника", "nick"), keep_blank_values=True))
    received = parsed.pop("hash")
    check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received)
    assert json.loads(parsed["user"])["id"] == 42


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


def test_settings_keep_secret_and_mask(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS", tmp_path / "settings.json")
    api = app.Api()
    api.save_settings({"bot_token": "123:SECRET9876", "voice_id": "v1"})
    shown = api.save_settings({"bot_token": "", "voice_id": "v2"})  # empty secret keeps the saved one
    assert app.load_settings()["bot_token"] == "123:SECRET9876"
    assert shown["bot_token"] == "••••9876" and shown["voice_id"] == "v2"
