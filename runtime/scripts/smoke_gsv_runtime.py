from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

FORBIDDEN_MODULES = ("backend", "fastapi", "sqlalchemy", "pytorch_lightning", "torchmetrics", "GPT_SoVITS.f5_tts")
logger = logging.getLogger(__name__)


def _assert_import_boundary() -> None:
    blocked = sorted(
        name for name in sys.modules
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULES)
    )
    if blocked:
        raise AssertionError(f"Runtime import boundary violated: {blocked}")


def _assert_audio(audio) -> int:
    import numpy as np

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32 and audio.ndim == 1 and audio.size > 0
    assert np.isfinite(audio).all()
    return int(audio.size)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify independent GSV imports and optional real inference.")
    parser.add_argument("--gpt", type=Path)
    parser.add_argument("--sovits", type=Path)
    parser.add_argument("--resources-root", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-text", default="This is a reference voice.")
    parser.add_argument("--reference-language", default="en")
    parser.add_argument("--text", default="Hello, this is an independent speech synthesis test.")
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float32")
    parser.add_argument("--require-g2pw", action="store_true")
    args = parser.parse_args()
    if bool(args.gpt) != bool(args.sovits):
        parser.error("--gpt and --sovits must be provided together")
    if args.reference and not args.gpt:
        parser.error("--reference requires model paths")
    if args.require_g2pw and not args.reference:
        parser.error("--require-g2pw requires a reference and Chinese inference text")

    from runtime.gsv import (
        BoundaryRequest,
        GSVRuntime,
        ModelSpec,
        ReferenceRequest,
        RenderConfig,
        RuntimeConfig,
        RuntimeDiagnosticCollector,
        SegmentRequest,
        SynthesisRequest,
    )
    from runtime.gsv.loader import NativeBackend

    runtime = GSVRuntime(RuntimeConfig(str(args.resources_root.resolve()), device=args.device, dtype=args.dtype))
    observer = RuntimeDiagnosticCollector()
    payload = {"package_root": str(PACKAGE_ROOT), "resources_root": runtime.config.resources_root}
    try:
        _assert_import_boundary()
        if args.gpt is None:
            payload["status"] = "imported"
        else:
            spec = ModelSpec(str(args.gpt.resolve()), str(args.sovits.resolve()))
            lease = runtime.load_model(spec, observer)
            backend = lease.backend
            assert isinstance(backend, NativeBackend)
            devices = [next(model.parameters()).device.type for model in (backend.t2s_model, backend.vq_model)]
            assert devices == [lease.identity.device, lease.identity.device]
            payload.update({
                "status": "loaded", "backend": type(backend).__name__, "device": lease.identity.device,
                "dtype": lease.identity.dtype, "parameter_devices": devices, "sample_rate": lease.identity.sample_rate,
            })
            if args.reference:
                import torch

                reference = ReferenceRequest(str(args.reference.resolve()), args.reference_text, args.reference_language)
                features = runtime.prepare_reference(lease, reference, observer=observer)
                for name in ("spectrogram", "speaker", "bert"):
                    assert isinstance(features.payload[name], torch.Tensor)
                    assert features.payload[name].device.type == "cpu"
                config = RenderConfig()
                left = runtime.render_segment(lease, SegmentRequest("left", args.text, args.language), features, config, observer=observer)
                right = runtime.render_segment(lease, SegmentRequest("right", args.text, args.language), features, config, observer=observer)
                boundary = runtime.render_boundary(lease, BoundaryRequest("edge", "left", "right"), left, right, features, config, observer=observer)
                crossfade = runtime.render_boundary(
                    lease, BoundaryRequest("crossfade", "left", "right", strategy="crossfade_only"),
                    left, right, features, config, observer=observer,
                )
                payload["samples"] = {
                    "left": _assert_audio(left.audio), "right": _assert_audio(right.audio),
                    "boundary": _assert_audio(boundary.audio), "crossfade": _assert_audio(crossfade.audio),
                }
                assert left.phones and left.semantic and left.trace["right_margin_frames"]
                converter = backend._delegate._g2pw
                if args.require_g2pw:
                    assert converter is not None, "Chinese inference did not use G2PW"
                if converter is not None:
                    providers = converter._g2pw.session_g2pW.get_providers()
                    expected = ["CUDAExecutionProvider", "CPUExecutionProvider"] if lease.identity.device == "cuda" else ["CPUExecutionProvider"]
                    assert providers == expected
                    payload["g2pw_providers"] = providers
                del converter
                runtime.release(lease)
                assert backend._delegate is None
                synthesis = runtime.synthesize(
                    SynthesisRequest(args.text, reference, language=args.language, model_spec=spec), observer=observer,
                )
                payload["samples"]["synthesis"] = _assert_audio(synthesis.audio)
                payload["status"] = "inferred"
            else:
                runtime.release(lease)
            _assert_import_boundary()
            assert not runtime._leases
        payload["checkpoints"] = sorted({event.checkpoint for event in observer.events()})
    except Exception as exc:
        logger.exception("Runtime smoke failed")
        info = getattr(exc, "info", None)
        payload.update({"status": "failed", "error_code": getattr(info, "error_code", type(exc).__name__), "message": str(exc)})
        print(json.dumps(payload, ensure_ascii=False))
        return 2
    finally:
        runtime.close()
    assert not runtime._leases and runtime._closed
    payload["closed"] = True
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
