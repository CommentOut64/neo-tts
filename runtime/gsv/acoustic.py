"""Acoustic and boundary backend protocol."""
from typing import Protocol


class AcousticBackend(Protocol):
    def render_boundary(self, request, left, right, features, config, control=None, observer=None): ...


__all__ = ["AcousticBackend"]
