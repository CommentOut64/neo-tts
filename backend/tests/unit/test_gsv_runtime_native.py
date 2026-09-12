import sys
import weakref
from types import ModuleType, SimpleNamespace

import pytest
import torch

from runtime.gsv import ModelSpec, RuntimeConfig, RuntimeFailure
from runtime.gsv.loader import (
    NativeBackend,
    _as_namespace,
    _load_checkpoint,
    _load_state_checked,
    _resolve_sovits_version,
)
from runtime.gsv.native import NativeInferenceBackend


class DeviceModule:
    def __init__(self):
        self.moves = []

    def to(self, *args, **kwargs):
        self.moves.append((args, kwargs))
        return self


def test_native_device_transfer_moves_models_and_loaded_frontends():
    backend = NativeInferenceBackend(
        t2s_model=DeviceModule(), vq_model=DeviceModule(),
        hps=SimpleNamespace(data=SimpleNamespace(sampling_rate=32000)),
        device="cpu", dtype=torch.float32, resources_root="unused",
    )
    backend._frontends_ready = True
    backend.ssl_model = DeviceModule()
    backend.bert_model = DeviceModule()
    backend.sv_model = SimpleNamespace(embedding_model=DeviceModule(), is_half=False)

    backend.move_to("cuda", torch.float16)
    assert backend.device == "cuda"
    assert backend.sv_model.is_half
    for model in (backend.t2s_model, backend.vq_model, backend.sv_model.embedding_model):
        assert model.moves[-1] == ((), {"device": "cuda", "dtype": torch.float16})
    for model in (backend.ssl_model, backend.bert_model):
        assert model.moves[-1] == ((), {"device": "cuda"})

    backend.move_to("cpu", torch.float32)
    assert backend.device == "cpu"
    assert not backend.sv_model.is_half
    for model in (backend.t2s_model, backend.vq_model, backend.sv_model.embedding_model):
        assert model.moves[-1] == ((), {"device": "cpu", "dtype": torch.float32})


def test_native_close_releases_model_storage_even_if_lease_is_retained():
    backend = NativeBackend.__new__(NativeBackend)
    backend._closed = False
    backend.t2s_model = torch.nn.Linear(2, 1)
    backend.vq_model = torch.nn.Linear(2, 1)
    references = [weakref.ref(backend.t2s_model), weakref.ref(backend.vq_model)]
    backend._delegate = NativeInferenceBackend(
        t2s_model=backend.t2s_model, vq_model=backend.vq_model,
        hps=SimpleNamespace(data=SimpleNamespace(sampling_rate=32000)),
        device="cpu", dtype=torch.float32, resources_root="unused",
    )
    backend.close()
    backend.close()
    assert all(reference() is None for reference in references)
    assert backend._delegate is None


def test_native_failed_initialization_releases_partial_models(tmp_path, monkeypatch):
    created = []
    references = []

    def fail_loading(self, spec, config):
        created.append(self)
        self.t2s_model = torch.nn.Linear(2, 1)
        references.append(weakref.ref(self.t2s_model))
        raise ValueError("checkpoint fixture failure")

    monkeypatch.setattr(NativeBackend, "_load_models", fail_loading)
    with pytest.raises(ValueError, match="checkpoint fixture failure"):
        NativeBackend(ModelSpec(str(tmp_path / "gpt"), str(tmp_path / "sovits")), RuntimeConfig(str(tmp_path)))
    assert created[0]._closed
    assert references[0]() is None


@pytest.mark.parametrize("defect, code", [
    ("missing", "CHECKPOINT_KEY_MISSING"),
    ("shape", "CHECKPOINT_SHAPE_MISMATCH"),
    ("unexpected", "MODEL_INCOMPATIBLE"),
])
def test_checkpoint_validation_distinguishes_missing_shape_and_extra_weights(defect, code):
    model = torch.nn.Linear(2, 1)
    before = model.weight.detach().clone()
    state = {key: value.clone() for key, value in model.state_dict().items()}
    if defect == "missing":
        del state["weight"]
    elif defect == "shape":
        state["weight"] = torch.zeros(3, 2)
    else:
        state["unrecognized"] = torch.zeros(1)
    with pytest.raises(RuntimeFailure) as error:
        _load_state_checked(model, state, allow_missing=())
    assert error.value.info.error_code == code
    assert torch.equal(model.weight, before)
    if defect == "shape":
        assert "weight: expected=(1, 2), checkpoint=(3, 2)" in str(error.value.__cause__)
        assert "checkpoint=(3, 2)" not in error.value.info.message


def test_inference_state_allows_only_explicit_training_residuals():
    model = torch.nn.Module()
    model.add_module("decoder", torch.nn.Linear(2, 1))
    model.add_module("enc_q", torch.nn.Linear(2, 1))
    state = {key: value.clone() for key, value in model.state_dict().items() if not key.startswith("enc_q.")}
    _load_state_checked(model, state, allow_missing=("enc_q.",))


@pytest.mark.parametrize("configured,header,vocabulary,speaker,expected", [
    (None, b"PK", 322, False, "v1"),
    (None, b"PK", 732, False, "v2"),
    (None, b"PK", 732, True, "v2Pro"),
    (None, b"05", 732, True, "v2Pro"),
    (None, b"06", 732, True, "v2ProPlus"),
    ("v1", b"PK", 322, False, "v1"),
    ("v2ProPlus", b"PK", 732, True, "v2ProPlus"),
])
def test_sovits_version_supports_legacy_and_tagged_checkpoints(configured, header, vocabulary, speaker, expected):
    hps = SimpleNamespace(model=SimpleNamespace())
    if configured is not None:
        hps.model.version = configured
    state = {"enc_p.text_embedding.weight": torch.zeros(vocabulary, 2)}
    if speaker:
        state["sv_emb.weight"] = torch.zeros(2, 4)
    assert _resolve_sovits_version(hps, state, header) == expected


@pytest.mark.parametrize("configured,header,vocabulary", [
    (None, b"PK", 11),
    ("v3", b"PK", 732),
    ("v2", b"03", 732),
    (None, b"04", 732),
    (None, b"99", 732),
])
def test_unknown_sovits_family_is_not_silently_assumed_to_be_v2(configured, header, vocabulary):
    hps = SimpleNamespace(model=SimpleNamespace(version=configured))
    state = {"enc_p.text_embedding.weight": torch.zeros(vocabulary, 2)}
    with pytest.raises(ValueError, match="Unsupported"):
        _resolve_sovits_version(hps, state, header)


def test_checkpoint_read_preserves_pro_plus_header_without_deserializing_twice(tmp_path, monkeypatch):
    path = tmp_path / "tagged.pth"
    torch.save({"config": {"model": {}}, "weight": {"sv_emb.weight": torch.zeros(2, 4)}}, path)
    payload = path.read_bytes()
    path.write_bytes(b"06" + payload[2:])
    loads = []
    original_load = torch.load

    def load(*args, **kwargs):
        loads.append(kwargs)
        return original_load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", load)
    checkpoint, header = _load_checkpoint(str(path))
    assert header == b"06"
    assert len(loads) == 1
    assert _resolve_sovits_version(_as_namespace(checkpoint["config"]), checkpoint["weight"], header) == "v2ProPlus"


def test_legacy_hparams_load_uses_packaged_class_without_global_utils_module(tmp_path, monkeypatch):
    from GPT_SoVITS.utils import HParams

    legacy_module = ModuleType("utils")
    legacy_module.HParams = HParams
    path = tmp_path / "legacy.pth"
    with monkeypatch.context() as legacy:
        legacy.setitem(sys.modules, "utils", legacy_module)
        legacy.setattr(HParams, "__module__", "utils")
        torch.save({"config": HParams(model={"version": "v1"}), "weight": {}}, path)

    unrelated_module = ModuleType("utils")
    monkeypatch.setitem(sys.modules, "utils", unrelated_module)
    checkpoint, header = _load_checkpoint(str(path))
    assert isinstance(checkpoint["config"], HParams)
    assert checkpoint["config"].model.version == "v1"
    assert header == b"PK"
    assert sys.modules["utils"] is unrelated_module
