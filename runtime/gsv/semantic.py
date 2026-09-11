"""Semantic backend protocol kept free of application imports."""
from typing import Protocol


class SemanticBackend(Protocol):
    def render_segment(self, request, features, config, control=None, observer=None): ...


__all__ = ["SemanticBackend"]
