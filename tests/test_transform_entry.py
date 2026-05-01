from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "skills" / "transform-skill" / "tools" / "transform_router.py"
RUNNER = ROOT / "skills" / "transform-skill" / "tools" / "run_transform.sh"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_path}:{existing}" if existing else src_path
    return env


def test_transform_router_doctor(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROUTER),
            "--action",
            "doctor",
            "--workspace-root",
            str(tmp_path),
            "--runtime-root",
            str(ROOT),
        ],
        cwd=str(ROOT),
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["entrypoint"] == "transform-skill"
    assert payload["action"] == "doctor"
    assert payload["semantic_intent"] == "friend-doctor"


def test_run_transform_list(tmp_path: Path) -> None:
    env = _env()
    env["TRANSFORM_WORKSPACE_ROOT"] = str(tmp_path)
    proc = subprocess.run(
        [str(RUNNER), "list"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["entrypoint"] == "transform-skill"
    assert payload["action"] == "list"
    assert payload["semantic_intent"] == "friend-list"
    assert payload["count"] == 0


def test_transform_skill_entry_hides_raw_json_by_default() -> None:
    skill_text = (ROOT / "skills" / "transform-skill" / "SKILL.md").read_text(encoding="utf-8")

    assert "Return both raw JSON" not in skill_text
    assert "默认不要把完整 JSON" in skill_text
    assert "debug" in skill_text.lower() or "doctor" in skill_text.lower()

def test_run_transform_prefers_python_310_plus_when_python3_is_older_or_broken(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python3 = fake_bin / "python3"
    fake_python3.write_text("#!/usr/bin/env bash\necho should-not-use-python3 >&2\nexit 99\n", encoding="utf-8")
    fake_python3.chmod(0o755)
    (fake_bin / "python3.10").symlink_to(Path(sys.executable))

    env = _env()
    env["TRANSFORM_WORKSPACE_ROOT"] = str(tmp_path / "workspace")
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        ["bash", str(RUNNER), "list"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "should-not-use-python3" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["action"] == "list"
