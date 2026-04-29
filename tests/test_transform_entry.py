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
