import re
from pathlib import Path

from backend.app.cli import build_parser, main


def test_backend_cli_defaults_to_launcher_port():
    parser = build_parser()

    args = parser.parse_args([])

    assert args.port == 18600


def test_frontend_dev_proxy_targets_env_or_launcher_port():
    source = Path("frontend/vite.config.ts").read_text(encoding="utf-8")

    assert 'loadEnv(mode, process.cwd(), "VITE_")' in source
    assert re.search(
        r'const\s+backendOrigin\s*=\s*env\.VITE_BACKEND_ORIGIN\s*\|\|\s*"http://127\.0\.0\.1:18600"',
        source,
    )
    assert source.count("target: backendOrigin") == 2


def test_start_dev_launcher_mentions_launcher_or_18600():
    source = Path("start_dev.bat").read_text(encoding="utf-8")

    assert "18600" in source


def test_backend_cli_disables_uvicorn_default_log_config(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr("backend.app.cli.uvicorn.run", fake_run)
    monkeypatch.setattr("sys.argv", ["backend.app.cli"])

    main()

    assert called["kwargs"]["log_config"] is None


def test_backend_cli_packaged_mode_does_not_enable_stdin_watchdog_by_default(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        called["kwargs"] = kwargs

    watchdog_state = {"started": False}

    def fake_watchdog() -> None:
        watchdog_state["started"] = True

    monkeypatch.setattr("backend.app.cli.uvicorn.run", fake_run)
    monkeypatch.setattr("backend.app.cli._start_stdin_watchdog", fake_watchdog)
    monkeypatch.setattr("sys.argv", ["backend.app.cli"])
    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")
    monkeypatch.delenv("NEO_TTS_STDIN_WATCHDOG_ENABLED", raising=False)

    main()

    assert watchdog_state["started"] is False
    assert called["kwargs"]["log_config"] is None


def test_backend_cli_can_enable_stdin_watchdog_with_explicit_env(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        called["kwargs"] = kwargs

    watchdog_state = {"started": False}

    def fake_watchdog() -> None:
        watchdog_state["started"] = True

    monkeypatch.setattr("backend.app.cli.uvicorn.run", fake_run)
    monkeypatch.setattr("backend.app.cli._start_stdin_watchdog", fake_watchdog)
    monkeypatch.setattr("sys.argv", ["backend.app.cli"])
    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")
    monkeypatch.setenv("NEO_TTS_STDIN_WATCHDOG_ENABLED", "1")

    main()

    assert watchdog_state["started"] is True
    assert called["kwargs"]["log_config"] is None
