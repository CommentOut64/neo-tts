from __future__ import annotations

from backend.app.services.owner_control_client import OwnerControlClient


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


def test_request_shutdown_posts_bearer_token(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("backend.app.services.owner_control_client.requests.post", fake_post)

    client = OwnerControlClient(
        origin="http://127.0.0.1:43125",
        token="owner-token",
        session_id="session-1",
    )

    client.request_shutdown(source="backend_prepare_exit")

    assert captured == {
        "url": "http://127.0.0.1:43125/v1/control/shutdown",
        "headers": {
            "Authorization": "Bearer owner-token",
            "X-Neo-TTS-Session-ID": "session-1",
        },
        "json": {"source": "backend_prepare_exit"},
        "timeout": 2,
    }


def test_request_shutdown_returns_false_when_origin_missing():
    client = OwnerControlClient(origin=None, token=None, session_id=None)

    assert client.request_shutdown(source="backend_prepare_exit") is False
