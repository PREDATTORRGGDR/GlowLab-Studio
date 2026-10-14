import app


def test_settings_keep_secret_and_mask(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS", tmp_path / "settings.json")
    api = app.Api()
    api.save_settings({"bot_token": "123:SECRET9876", "voice_id": "v1"})
    shown = api.save_settings({"bot_token": "", "voice_id": "v2"})  # empty secret keeps the saved one
    assert app.load_settings()["bot_token"] == "123:SECRET9876"
    assert shown["bot_token"] == "••••9876" and shown["voice_id"] == "v2"
