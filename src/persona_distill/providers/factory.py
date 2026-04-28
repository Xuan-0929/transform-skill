from __future__ import annotations

from .base import ModelProvider
from .heuristic import HeuristicProvider


RUNTIME_SPEC = "runtime:skill"


def resolve_runtime_spec() -> str:
    return RUNTIME_SPEC


def build_provider() -> ModelProvider:
    # Skill-native single path: runtime-only provider.
    return HeuristicProvider()
