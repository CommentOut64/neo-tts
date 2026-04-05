from pathlib import Path

from backend.app.cli import build_parser, main


def test_backend_cli_defaults_to_fastapi_mainline_port():
    parser = build_parser()

    args = parser.parse_args([])

    assert args.port == 8000


def test_frontend_dev_proxy_targets_fastapi_mainline_port():
    source = Path("frontend/vite.config.ts").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8000" in source
    assert "http://127.0.0.1:8001" not in source


def test_start_dev_launcher_targets_fastapi_mainline_port():
    source = Path("start_dev.bat").read_text(encoding="utf-8")

    assert "8000" in source
    assert "8001" not in source


def test_backend_cli_disables_uvicorn_default_log_config(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr("backend.app.cli.uvicorn.run", fake_run)
    monkeypatch.setattr("sys.argv", ["backend.app.cli"])

    main()

    assert called["kwargs"]["log_config"] is None
