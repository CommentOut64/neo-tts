from __future__ import annotations

import argparse
import os

from backend.app.main import create_app


# legacy 兼容入口：保留 `api_server:app` 供旧启动命令继续可用
app = create_app()


def _apply_legacy_env_overrides(args: argparse.Namespace) -> None:
    if args.voices_config:
        os.environ["GPT_SOVITS_VOICES_CONFIG"] = args.voices_config
    if args.cnhubert_path:
        os.environ["CNHUBERT_PATH"] = args.cnhubert_path
    if args.bert_path:
        os.environ["BERT_PATH"] = args.bert_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GPT-SoVITS API Server (legacy compatibility)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--voices_config")
    parser.add_argument("--cnhubert_path")
    parser.add_argument("--bert_path")
    return parser


if __name__ == "__main__":
    import uvicorn

    cli_args = _build_parser().parse_args()
    _apply_legacy_env_overrides(cli_args)
    uvicorn.run(
        "backend.app.main:create_app",
        factory=True,
        host=cli_args.host,
        port=cli_args.port,
        reload=cli_args.reload,
    )
