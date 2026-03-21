import importlib
import sys

from fastapi.testclient import TestClient


def test_legacy_api_server_delegates_to_rebuild_app(sample_voice_config, monkeypatch):
    monkeypatch.setenv("GPT_SOVITS_VOICES_CONFIG", str(sample_voice_config))

    if "api_server" in sys.modules:
        del sys.modules["api_server"]
    api_server = importlib.import_module("api_server")

    client = TestClient(api_server.app)
    response = client.get("/health")

    assert api_server.app.title == "GPT-SoVITS Rebuild Backend"
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
