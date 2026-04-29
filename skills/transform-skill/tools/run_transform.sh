#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  cat >&2 <<'USAGE'
Usage: run_transform.sh <action> [options]

Actions:
  create | update | list | history | rollback | export | correct | doctor

Examples:
  run_transform.sh update --input ./corpus/incoming/new.json --friend-id friend-alex --target-speaker Alex --new-corpus-weight 0.2
  run_transform.sh list
USAGE
  exit 1
fi

ACTION="$1"
shift || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

resolve_runtime_root() {
  local candidate=""

  if [[ -n "${DISTILL_PROJECT_ROOT:-}" ]]; then
    candidate="$DISTILL_PROJECT_ROOT"
    if [[ -d "$candidate/src/persona_distill" ]]; then
      echo "$candidate"
      return 0
    fi
  fi

  candidate="$PWD"
  if [[ -d "$candidate/src/persona_distill" ]]; then
    echo "$candidate"
    return 0
  fi

  candidate="$SKILL_DIR/runtime"
  if [[ -d "$candidate/src/persona_distill" ]]; then
    echo "$candidate"
    return 0
  fi

  candidate="$SKILL_DIR/../distill-from-corpus-path/runtime"
  if [[ -d "$candidate/src/persona_distill" ]]; then
    echo "$candidate"
    return 0
  fi

  candidate="$SKILL_DIR/../.."
  if [[ -d "$candidate/src/persona_distill" ]]; then
    echo "$candidate"
    return 0
  fi

  return 1
}

RUNTIME_ROOT="$(resolve_runtime_root || true)"
if [[ -z "$RUNTIME_ROOT" ]]; then
  cat >&2 <<'ERR'
Cannot locate persona_distill runtime.
Checked:
1) DISTILL_PROJECT_ROOT
2) current working directory
3) transform-skill/runtime
4) distill-from-corpus-path/runtime
5) repo root (../../)
ERR
  exit 2
fi

PYTHON_BIN="python3"
RUNTIME_REQ="$RUNTIME_ROOT/requirements.txt"
if [[ -f "$RUNTIME_REQ" ]]; then
  if ! PYTHONPATH="$RUNTIME_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import typer, pydantic, yaml
PY
  then
    if [[ "${DISTILL_AUTO_BOOTSTRAP:-0}" == "1" ]]; then
      VENV_DIR="$RUNTIME_ROOT/.venv"
      if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR"
      fi
      "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
      "$VENV_DIR/bin/python" -m pip install -r "$RUNTIME_REQ" >/dev/null
      PYTHON_BIN="$VENV_DIR/bin/python"
    else
      cat >&2 <<'ERR'
Python dependencies are missing.
Install with:
  pip3 install -r skills/transform-skill/runtime/requirements.txt
Or enable auto bootstrap:
  DISTILL_AUTO_BOOTSTRAP=1
ERR
      exit 2
    fi
  fi
fi

WORKSPACE_ROOT="${TRANSFORM_WORKSPACE_ROOT:-$PWD}"

CMD=(
  "$PYTHON_BIN" "$SCRIPT_DIR/transform_router.py"
  --action "$ACTION"
  --workspace-root "$WORKSPACE_ROOT"
  --runtime-root "$RUNTIME_ROOT"
)

if [[ $# -gt 0 ]]; then
  CMD+=("$@")
fi

(
  cd "$RUNTIME_ROOT"
  export PYTHONPATH="$RUNTIME_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  "${CMD[@]}"
)
