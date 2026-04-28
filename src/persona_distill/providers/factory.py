from __future__ import annotations

import os

from .claude_code import ClaudeCodeProvider
from .base import ModelProvider


RUNTIME_SPEC = "runtime:skill"


def resolve_runtime_spec() -> str:
    return RUNTIME_SPEC


def build_provider() -> ModelProvider:
    # Skill-native single path: use local Claude Code runtime.
    model = os.environ.get("DISTILL_CLAUDE_MODEL") or None
    timeout = int(os.environ.get("DISTILL_CLAUDE_TIMEOUT_SEC", "90"))
    return ClaudeCodeProvider(model=model, timeout_sec=timeout)
