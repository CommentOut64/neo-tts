"""CPU-only reference component cache owned by a :class:`GSVRuntime`."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
import copy
import threading

import numpy as np


class ReferenceComponentCache:
    """LRU cache that never retains or returns backend/device tensors."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[tuple[str, ...], object] = OrderedDict()
        self._sizes: dict[tuple[str, ...], int] = {}
        self._bytes = 0
        self._lock = threading.RLock()

    def get(self, key: tuple[str, ...]):
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                return None
            self._entries.move_to_end(key)
            return cpu_clone(value)

    def put(self, key: tuple[str, ...], value) -> None:
        cloned = cpu_clone(value)
        size = cpu_nbytes(cloned)
        with self._lock:
            self._bytes -= self._sizes.pop(key, 0)
            self._entries[key] = cloned
            self._sizes[key] = size
            self._bytes += size
            self._entries.move_to_end(key)
            while self._entries and (len(self._entries) > self._max_entries or self._bytes > self._max_bytes):
                evicted, _ = self._entries.popitem(last=False)
                self._bytes -= self._sizes.pop(evicted, 0)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sizes.clear()
            self._bytes = 0


def cpu_clone(value):
    import torch

    if isinstance(value, torch.Tensor):
        dtype = torch.float32 if value.is_floating_point() else value.dtype
        return value.detach().to(device="cpu", dtype=dtype).clone()
    if isinstance(value, np.ndarray):
        return value.copy()
    if isinstance(value, Mapping):
        return {key: cpu_clone(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(cpu_clone(item) for item in value)
    if isinstance(value, list):
        return [cpu_clone(item) for item in value]
    if is_dataclass(value):
        return replace(value, **{field.name: cpu_clone(getattr(value, field.name)) for field in fields(value)})
    return copy.deepcopy(value)


def cpu_nbytes(value) -> int:
    import torch

    if isinstance(value, torch.Tensor):
        return value.numel() * value.element_size()
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, Mapping):
        return sum(cpu_nbytes(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return sum(cpu_nbytes(item) for item in value)
    return 0
