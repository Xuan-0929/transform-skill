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

python_supports_runtime() {
  local candidate="$1"
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

select_python_bin() {
  local candidate=""
  local resolved=""

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if python_supports_runtime "$PYTHON_BIN"; then
      echo "$PYTHON_BIN"
      return 0
    fi
    echo "PYTHON_BIN must point to Python >= 3.10: $PYTHON_BIN" >&2
    return 1
  fi

  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    resolved="$(command -v "$candidate")"
    if python_supports_runtime "$resolved"; then
      echo "$resolved"
      return 0
    fi
  done

  echo "Cannot find Python >= 3.10. transform-skill requires Python 3.10+." >&2
  return 1
}

PYTHON_BIN="$(select_python_bin)"
RUNTIME_REQ="$RUNTIME_ROOT/requirements.txt"
if [[ -f "$RUNTIME_REQ" ]]; then
  if ! PYTHONPATH="$RUNTIME_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import typer, pydantic, yaml
PY
  then
    if [[ "${DISTILL_AUTO_BOOTSTRAP:-0}" == "1" ]]; then
      VENV_DIR="${DISTILL_VENV_DIR:-$RUNTIME_ROOT/.venv-py310}"
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
