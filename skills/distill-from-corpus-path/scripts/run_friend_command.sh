#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: run_friend_command.sh <intent> [corpus_path] [persona_id] [target_speaker]" >&2
  echo "Example: run_friend_command.sh friend-update ./corpus/new.json friend-alex Alex" >&2
  exit 1
fi

INTENT="$1"
INPUT_PATH="${2:-}"
PERSONA_ID="${3:-}"
TARGET_SPEAKER="${4:-}"

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
DISTILL_NEW_WEIGHT_VALUE="${DISTILL_NEW_CORPUS_WEIGHT:-0.25}"
DISTILL_HISTORY_LIMIT_VALUE="${DISTILL_HISTORY_LIMIT:-20}"

if [[ "$INTENT" == "friend-create" || "$INTENT" == "friend-update" || "$INTENT" == "create-friend" || "$INTENT" == "update-friend" ]]; then
  if ! command -v claude >/dev/null 2>&1; then
    echo "Claude CLI not found. Install Claude Code CLI first." >&2
    exit 2
  fi
  if [[ "${DISTILL_PRECHECK_CLAUDE_AUTH:-0}" == "1" && "${DISTILL_SKIP_CLAUDE_AUTH_CHECK:-0}" != "1" ]]; then
    AUTH_STATUS="$(claude auth status 2>/dev/null || true)"
    if [[ "$AUTH_STATUS" != *'"loggedIn": true'* ]]; then
      echo "Claude CLI is not logged in. Run: claude auth login" >&2
      exit 2
    fi
  fi
fi

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

CMD=(
  "$PYTHON_BIN" -m persona_distill friend
  --intent "$INTENT"
  --format "$DISTILL_FORMAT_VALUE"
  --target "$DISTILL_TARGET_VALUE"
  --new-corpus-weight "$DISTILL_NEW_WEIGHT_VALUE"
  --history-limit "$DISTILL_HISTORY_LIMIT_VALUE"
)

if [[ -n "$INPUT_PATH" ]]; then
  CMD+=(--input "$INPUT_PATH")
fi

if [[ -n "$PERSONA_ID" ]]; then
  CMD+=(--persona "$PERSONA_ID")
fi

if [[ -n "$TARGET_SPEAKER" ]]; then
  CMD+=(--speaker "$TARGET_SPEAKER")
elif [[ -n "${DISTILL_SPEAKER:-}" ]]; then
  CMD+=(--speaker "$DISTILL_SPEAKER")
fi

if [[ -n "${DISTILL_EVAL_SUITE:-}" ]]; then
  CMD+=(--suite "$DISTILL_EVAL_SUITE")
fi

if [[ -n "${DISTILL_TO_VERSION:-}" ]]; then
  CMD+=(--to "$DISTILL_TO_VERSION")
fi

if [[ -n "${DISTILL_CORRECTION_TEXT:-}" ]]; then
  CMD+=(--text "$DISTILL_CORRECTION_TEXT")
fi

if [[ -n "${DISTILL_CORRECTION_SECTION:-}" ]]; then
  CMD+=(--correction-section "$DISTILL_CORRECTION_SECTION")
fi

(
  cd "$PROJECT_ROOT"
  export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  "${CMD[@]}"
)
