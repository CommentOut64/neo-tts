from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_legacy_audio_write_endpoints_are_not_registered(test_app_settings):
    application = create_app(settings=test_app_settings)

    with TestClient(application) as client:
        speech_response = client.post(
            "/v1/audio/speech",
            json={
                "input": "hello world",
                "voice": "demo",
            },
        )
        result_delete_response = client.delete("/v1/audio/results/result-1")

    assert speech_response.status_code == 404
    assert result_delete_response.status_code == 404
