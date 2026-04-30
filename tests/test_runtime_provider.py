from __future__ import annotations

import pytest

from persona_distill.providers.claude_code import resolve_runtime_cli
from persona_distill.providers.factory import build_provider, resolve_runtime_spec


def test_resolve_runtime_cli_prefers_codex_in_codex_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_SHELL", "1")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"codex", "claude"} else None

    monkeypatch.setattr("persona_distill.providers.claude_code.shutil.which", _which)
    assert resolve_runtime_cli("auto") == "codex"


def test_resolve_runtime_cli_prefers_claude_in_generic_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_SHELL", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"codex", "claude"} else None

    monkeypatch.setattr("persona_distill.providers.claude_code.shutil.which", _which)
    assert resolve_runtime_cli("auto") == "claude"


def test_resolve_runtime_cli_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        resolve_runtime_cli("invalid")


def test_resolve_runtime_spec_reflects_runtime_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_RUNTIME_CLI", "codex")
    assert resolve_runtime_spec() == "runtime:skill/codex"


def test_build_provider_uses_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_RUNTIME_CLI", "codex")
    monkeypatch.setenv("DISTILL_MODEL", "gpt-5.5")
    monkeypatch.setenv("DISTILL_RUNTIME_TIMEOUT_SEC", "123")
    provider = build_provider()
    assert getattr(provider, "runtime_cli") == "codex"
    assert provider.model == "gpt-5.5"
    assert getattr(provider, "timeout_sec") == 123
