from __future__ import annotations

from pathlib import Path

from persona_distill.cli import _repo


def test_repo_uses_transform_workspace_root_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRANSFORM_WORKSPACE_ROOT", str(tmp_path))

    repo = _repo()

    assert repo.root == tmp_path.resolve()
