from __future__ import annotations

import hashlib
import pickle
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .diagnostics import bind_model, cleanup_operation, runtime_entrypoint
from .errors import RuntimeFailure, RuntimePhase, error_info, fail, report_failure, runtime_checkpoint
from .types import ModelIdentity, ModelLease, ModelSpec, RuntimeConfig


def _revision(path: str) -> str:
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with file.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _as_namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_as_namespace(item) for item in value]
    return value


class _CheckpointUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module == "utils" and name == "HParams":
            from GPT_SoVITS.utils import HParams

            return HParams
        return super().find_class(module, name)


def _load_checkpoint(path: str, *, checkpoint: str = "model.deserialize"):
    import torch

    with open(path, "rb") as handle:
        prefix = handle.read(2)
        payload = handle.read()
    if prefix != b"PK":
        payload = b"PK" + payload
    else:
        payload = prefix + payload
    checkpoint_pickle = SimpleNamespace(
        __name__="pickle", Unpickler=_CheckpointUnpickler, load=pickle.load,
    )
    with runtime_checkpoint(None, RuntimePhase.MODEL, checkpoint, "CHECKPOINT_CORRUPTED"):
        loaded = torch.load(BytesIO(payload), map_location="cpu", weights_only=False, pickle_module=checkpoint_pickle)
    return loaded, prefix


def _resolve_sovits_version(hps, state: dict[str, Any], header: bytes) -> str:
    header_versions = {
        b"00": "v1", b"01": "v2", b"02": "v3", b"03": "v3",
        b"04": "v4", b"05": "v2Pro", b"06": "v2ProPlus",
    }
    supported = {"v1", "v2", "v2Pro", "v2ProPlus"}
    tagged = header_versions.get(header)
    if (header != b"PK" and tagged is None) or (tagged is not None and tagged not in supported):
        raise ValueError("Unsupported SoVITS checkpoint version header")
    configured = getattr(hps.model, "version", None) or getattr(hps, "version", None)
    version = configured or tagged
    if version is None:
        if "sv_emb.weight" in state:
            version = "v2Pro"
        else:
            from GPT_SoVITS.text import symbols, symbols2

            embedding = state.get("enc_p.text_embedding.weight")
            if embedding is not None and embedding.ndim == 2:
                version = {
                    len(symbols.symbols): "v1",
                    len(symbols2.symbols): "v2",
                }.get(embedding.shape[0])
    if version not in supported:
        raise ValueError("Unsupported or unidentified SoVITS model version")
    return version


def _resolve_device(config: RuntimeConfig) -> str:
    if config.device != "auto":
        if config.device == "cuda":
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is not available")
        return config.device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


class NativeBackend:
    """Standalone GPT/SoVITS checkpoint assembly with no application imports."""

    _SOVITS_MISSING_ALLOWLIST = ("enc_q.",)

    def __init__(self, spec: ModelSpec, config: RuntimeConfig) -> None:
        self._closed = False
        self.t2s_model = None
        self.vq_model = None
        self._delegate = None
        try:
            self._load_models(spec, config)
        except BaseException:
            cleanup_operation("model.partial_release", self.close)
            raise

    def _load_models(self, spec: ModelSpec, config: RuntimeConfig) -> None:
        import torch

        from GPT_SoVITS.AR.models.t2s_model import Text2SemanticDecoder
        from GPT_SoVITS.module.models import SynthesizerTrn

        self.device = _resolve_device(config)
        self.dtype = torch.float16 if self.device == "cuda" and config.dtype in {"float16", "half"} else torch.float32
        bind_model(device=self.device, dtype=str(self.dtype).removeprefix("torch."))
        gpt_checkpoint, _ = _load_checkpoint(spec.gpt_path, checkpoint="model.gpt.deserialize")
        sovits_checkpoint, sovits_header = _load_checkpoint(spec.sovits_path, checkpoint="model.sovits.deserialize")
        if not isinstance(gpt_checkpoint, dict) or not isinstance(gpt_checkpoint.get("weight"), dict):
            raise RuntimeFailure(error_info("CHECKPOINT_KEY_MISSING", checkpoint="model.load", message="GPT checkpoint must contain a weight mapping."))
        if not isinstance(sovits_checkpoint, dict) or not isinstance(sovits_checkpoint.get("weight"), dict):
            raise RuntimeFailure(error_info("CHECKPOINT_KEY_MISSING", checkpoint="model.load", message="SoVITS checkpoint must contain a weight mapping."))

        self.config = gpt_checkpoint.get("config")
        if not isinstance(self.config, dict) or not isinstance(self.config.get("model"), dict):
            raise RuntimeFailure(error_info("CHECKPOINT_KEY_MISSING", checkpoint="model.load", message="GPT checkpoint model configuration is missing."))
        with runtime_checkpoint(None, RuntimePhase.MODEL, "model.gpt.construct", "MODEL_LOAD_FAILED"):
            self.t2s_model = Text2SemanticDecoder(self.config, top_k=3)
        gpt_state = {
            key.removeprefix("model."): value
            for key, value in gpt_checkpoint["weight"].items()
        }
        if len(gpt_state) != len(gpt_checkpoint["weight"]):
            raise ValueError("GPT checkpoint has duplicate normalized keys")
        with runtime_checkpoint(None, RuntimePhase.MODEL, "model.gpt.weights", "CHECKPOINT_KEY_MISSING"):
            _load_state_checked(self.t2s_model, gpt_state, allow_missing=())

        self.hps = _as_namespace(sovits_checkpoint.get("config", {}))
        model_config = getattr(self.hps, "model", None)
        data_config = getattr(self.hps, "data", None)
        train_config = getattr(self.hps, "train", None)
        if model_config is None or data_config is None or train_config is None:
            raise RuntimeFailure(error_info("CHECKPOINT_KEY_MISSING", checkpoint="model.sovits.config", message="SoVITS checkpoint configuration is incomplete."))
        model_version = _resolve_sovits_version(self.hps, sovits_checkpoint["weight"], sovits_header)
        model_config.semantic_frame_rate = "25hz"
        model_config.version = model_version
        with runtime_checkpoint(None, RuntimePhase.MODEL, "model.sovits.construct", "MODEL_LOAD_FAILED"):
            self.vq_model = SynthesizerTrn(
                data_config.filter_length // 2 + 1,
                train_config.segment_size // data_config.hop_length,
                n_speakers=data_config.n_speakers,
                **vars(model_config),
            )
        with runtime_checkpoint(None, RuntimePhase.MODEL, "model.sovits.weights", "CHECKPOINT_KEY_MISSING"):
            _load_state_checked(self.vq_model, sovits_checkpoint["weight"], allow_missing=self._SOVITS_MISSING_ALLOWLIST)
        self.sample_rate = int(data_config.sampling_rate)
        with runtime_checkpoint(None, RuntimePhase.DEVICE, "device.models", "DEVICE_TRANSFER_FAILED"):
            self.t2s_model.to(device=self.device, dtype=self.dtype).eval()
            self.vq_model.to(device=self.device, dtype=self.dtype).eval()
        from .native import NativeInferenceBackend

        self._delegate = NativeInferenceBackend(
            t2s_model=self.t2s_model,
            vq_model=self.vq_model,
            hps=self.hps,
            device=self.device,
            dtype=self.dtype,
            resources_root=config.resources_root,
            cnhubert_path=config.cnhubert_path,
            bert_path=config.bert_path,
        )
        self._closed = False

    def prepare_reference(self, request, control=None, observer=None):
        return self._delegate.prepare_reference(request, control, observer)

    def render_segment(self, request, features, config, control=None, observer=None):
        return self._delegate.render_segment(request, features, config, control, observer)

    def render_boundary(self, request, left, right, features, config, control=None, observer=None):
        return self._delegate.render_boundary(request, left, right, features, config, control, observer)

    def synthesize(self, request, control=None, observer=None):
        return self._delegate.synthesize(request, control, observer)

    def move_to(self, device: str, dtype: str) -> None:
        import torch

        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available")
        target_dtype = torch.float16 if device == "cuda" and dtype in {"float16", "half"} else torch.float32
        previous_device, previous_dtype = self.device, self.dtype
        try:
            self._delegate.move_to(device, target_dtype)
        except Exception:
            cleanup_operation("device.rollback", lambda: self._delegate.move_to(previous_device, previous_dtype))
            raise
        self.device, self.dtype = device, target_dtype

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._delegate is not None:
                self._delegate.close()
        finally:
            self._delegate = None
            self.t2s_model = None
            self.vq_model = None


def _load_state_checked(module, state: dict[str, Any], *, allow_missing: tuple[str, ...]) -> None:
    expected = module.state_dict()
    missing = sorted(set(expected) - set(state))
    unexpected = sorted(set(state) - set(expected))
    disallowed_missing = [key for key in missing if not any(key.startswith(prefix) for prefix in allow_missing)]
    shape_errors = [
        key for key in sorted(set(expected).intersection(state))
        if tuple(expected[key].shape) != tuple(state[key].shape)
    ]
    if disallowed_missing:
        cause = ValueError(f"{type(module).__name__}: missing {len(disallowed_missing)} required weights; {disallowed_missing[:16]}")
        raise RuntimeFailure(error_info("CHECKPOINT_KEY_MISSING", checkpoint="model.state", message="Checkpoint is missing required inference weights."), cause) from cause
    if shape_errors:
        mismatch_details = "; ".join(
            f"{key}: expected={tuple(expected[key].shape)}, checkpoint={tuple(state[key].shape)}"
            for key in shape_errors[:16]
        )
        cause = ValueError(f"{type(module).__name__}: {len(shape_errors)} mismatched weight shapes; {mismatch_details}")
        raise RuntimeFailure(error_info("CHECKPOINT_SHAPE_MISMATCH", checkpoint="model.state", message="Checkpoint weight shapes do not match the model."), cause) from cause
    if unexpected:
        cause = ValueError(f"{type(module).__name__}: unexpected {len(unexpected)} weights; {unexpected[:16]}")
        raise RuntimeFailure(error_info("MODEL_INCOMPATIBLE", checkpoint="model.state", message="Checkpoint contains unsupported weights."), cause) from cause
    module.load_state_dict(state, strict=not missing)


@runtime_entrypoint(RuntimePhase.MODEL, "model.assemble", "MODEL_LOAD_FAILED")
def load_model(spec: ModelSpec, config: RuntimeConfig, observer=None, backend_factory=None) -> ModelLease:
    bind_model(device=config.device, dtype=config.dtype)
    backend = None
    published = False
    try:
        with runtime_checkpoint(observer, RuntimePhase.MODEL, "model.resolve", "MODEL_NOT_FOUND"):
            gpt_revision = _revision(spec.gpt_path)
            sovits_revision = _revision(spec.sovits_path)
        bind_model(model_revision=spec.model_revision or f"{gpt_revision}:{sovits_revision}", device=config.device, dtype=config.dtype)
        backend = backend_factory(spec, config) if backend_factory is not None else NativeBackend(spec, config)
        data = getattr(getattr(getattr(backend, "engine", backend), "hps", None), "data", None)
        sample_rate = int(getattr(data, "sampling_rate", getattr(backend, "sample_rate", 32000)))
        if sample_rate <= 0:
            raise ValueError("invalid sample rate")
        resolved_device = getattr(backend, "device", config.device)
        detected_version = str(getattr(getattr(backend, "hps", None), "model", SimpleNamespace(version="unknown")).version)
        capabilities = spec.capabilities or (
            "gpt_semantic_25hz",
            f"sovits_{detected_version}",
            "segment_trace",
            "boundary_prefix",
            "crossfade_only",
        )
        resolved_dtype = str(getattr(backend, "dtype", config.dtype)).removeprefix("torch.")
        identity = ModelIdentity(gpt_revision, sovits_revision, sample_rate, quantizer=detected_version, device=resolved_device, dtype=resolved_dtype, capabilities=capabilities)
        lease = ModelLease(str(uuid.uuid4()), spec, identity, backend)
        bind_model(lease)
        published = True
        return lease
    except RuntimeFailure as exc:
        raise report_failure(observer, exc)
    except FileNotFoundError as exc:
        info = error_info("MODEL_NOT_FOUND", checkpoint="model.load", message="Model resource is missing.", details={"resource": Path(str(exc)).name})
        raise fail(observer, info, exc) from exc
    except ValueError as exc:
        message = str(exc)
        if "sample rate" in message:
            code = "INVALID_SAMPLE_RATE"
        elif "shape" in message:
            code = "CHECKPOINT_SHAPE_MISMATCH"
        elif "weight" in message or "missing" in message or "unexpected" in message:
            code = "CHECKPOINT_KEY_MISSING"
        else:
            code = "MODEL_INCOMPATIBLE"
        info = error_info(code, checkpoint="model.load", message="Checkpoint does not match the supported inference contract.")
        raise fail(observer, info, exc) from exc
    except (RuntimeError, OSError) as exc:
        code = "DEVICE_UNAVAILABLE" if "CUDA" in str(exc) or "device" in str(exc).lower() else "MODEL_LOAD_FAILED"
        info = error_info(code, checkpoint="model.load", message="Model could not be loaded.")
        raise fail(observer, info, exc) from exc
    except Exception as exc:
        info = error_info("MODEL_LOAD_FAILED", checkpoint="model.load", message="Model could not be loaded.")
        raise fail(observer, info, exc) from exc
    finally:
        if not published and backend is not None:
            close = getattr(backend, "close", None)
            if callable(close):
                cleanup_operation("model.unpublished_release", close)
