from __future__ import annotations

import os

from .claude_code import ClaudeCodeProvider, resolve_runtime_cli
from .base import ModelProvider


RUNTIME_SPEC = "runtime:skill"


def resolve_runtime_spec() -> str:
    runtime_cli = resolve_runtime_cli(os.environ.get("DISTILL_RUNTIME_CLI", "auto"))
    return f"{RUNTIME_SPEC}/{runtime_cli}"


def build_provider() -> ModelProvider:
    # Skill-native single path: use host runtime CLI (Codex or Claude).
    runtime_cli = os.environ.get("DISTILL_RUNTIME_CLI", "auto")
    model = os.environ.get("DISTILL_MODEL") or os.environ.get("DISTILL_CLAUDE_MODEL") or None
    timeout_raw = os.environ.get("DISTILL_RUNTIME_TIMEOUT_SEC") or os.environ.get("DISTILL_CLAUDE_TIMEOUT_SEC")
    timeout = int(timeout_raw or "90")
    return ClaudeCodeProvider(runtime_cli=runtime_cli, model=model, timeout_sec=timeout)
