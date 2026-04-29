#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: run_agent_orchestrated.sh <corpus_path> [persona_id] [speaker]" >&2
  exit 1
fi

INPUT_PATH="$1"
PERSONA_ID="${2:-}"
SPEAKER_FILTER="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

resolve_project_root() {
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

  if [[ -n "${CLAUDE_SKILL_DIR:-}" ]]; then
    candidate="$CLAUDE_SKILL_DIR/runtime"
    if [[ -d "$candidate/src/persona_distill" ]]; then
      echo "$candidate"
      return 0
    fi
  fi

  candidate="$SKILL_DIR/runtime"
  if [[ -d "$candidate/src/persona_distill" ]]; then
    echo "$candidate"
    return 0
  fi

  return 1
}

PROJECT_ROOT="$(resolve_project_root || true)"
if [[ -z "$PROJECT_ROOT" ]]; then
  cat >&2 <<'ERR'
Cannot locate distillation runtime root.
Tried:
1) DISTILL_PROJECT_ROOT
2) current working directory
3) CLAUDE_SKILL_DIR/runtime
4) skill-local runtime

Fix:
- set DISTILL_PROJECT_ROOT to a directory containing src/persona_distill, or
- install this skill with OpenSkills so bundled runtime is present.
ERR
  exit 1
fi

DISTILL_TARGET_VALUE="${DISTILL_EXPORT_TARGET:-both}"
DISTILL_FORMAT_VALUE="${DISTILL_FORMAT:-auto}"
DISTILL_NEW_WEIGHT_VALUE="${DISTILL_NEW_CORPUS_WEIGHT:-}"

PYTHON_BIN="python3"
RUNTIME_REQ="$PROJECT_ROOT/requirements.txt"
if [[ ! -f "$RUNTIME_REQ" && -f "$SKILL_DIR/runtime/requirements.txt" ]]; then
  RUNTIME_REQ="$SKILL_DIR/runtime/requirements.txt"
fi

if [[ -f "$RUNTIME_REQ" ]]; then
  if ! PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import typer, pydantic, yaml
PY
  then
    if [[ "${DISTILL_AUTO_BOOTSTRAP:-0}" == "1" ]]; then
      VENV_DIR="$PROJECT_ROOT/.venv"
      if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR"
      fi
      "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
      "$VENV_DIR/bin/python" -m pip install -r "$RUNTIME_REQ" >/dev/null
      PYTHON_BIN="$VENV_DIR/bin/python"
    else
      cat >&2 <<'ERR'
Python dependencies are missing.
Install optional runtime deps with:
  pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
Or enable auto bootstrap:
  DISTILL_AUTO_BOOTSTRAP=1
ERR
      exit 2
    fi
  fi
fi

CMD=("$PYTHON_BIN" -m persona_distill orchestrate --input "$INPUT_PATH" --format "$DISTILL_FORMAT_VALUE" --target "$DISTILL_TARGET_VALUE")

if [[ -n "$PERSONA_ID" ]]; then
  CMD+=(--persona "$PERSONA_ID")
fi

if [[ -n "$SPEAKER_FILTER" ]]; then
  CMD+=(--speaker "$SPEAKER_FILTER")
fi

if [[ -n "${DISTILL_EVAL_SUITE:-}" ]]; then
  CMD+=(--suite "$DISTILL_EVAL_SUITE")
fi

if [[ -n "$DISTILL_NEW_WEIGHT_VALUE" ]]; then
  CMD+=(--new-corpus-weight "$DISTILL_NEW_WEIGHT_VALUE")
fi

(
  cd "$PROJECT_ROOT"
  export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  "${CMD[@]}"
)
