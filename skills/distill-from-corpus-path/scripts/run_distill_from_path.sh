#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: run_distill_from_path.sh <corpus_path> [persona_id] [speaker]" >&2
  exit 1
fi

INPUT_PATH="$1"
PERSONA_ID="${2:-}"
SPEAKER_FILTER="${3:-}"

PROJECT_ROOT="${DISTILL_PROJECT_ROOT:-$PWD}"
if [[ ! -f "$PROJECT_ROOT/pyproject.toml" || ! -d "$PROJECT_ROOT/src/persona_distill" ]]; then
  echo "Cannot locate persona-distill project root. Set DISTILL_PROJECT_ROOT first." >&2
  exit 1
fi

DISTILL_TARGET_VALUE="${DISTILL_EXPORT_TARGET:-both}"
DISTILL_FORMAT_VALUE="${DISTILL_FORMAT:-auto}"
DISTILL_NEW_WEIGHT_VALUE="${DISTILL_NEW_CORPUS_WEIGHT:-}"

# Always execute the local source-tree runtime to avoid accidentally using
# an unrelated globally installed `distill` executable.
CLI=(python3 -m persona_distill)

CMD=("${CLI[@]}" run --input "$INPUT_PATH" --format "$DISTILL_FORMAT_VALUE" --target "$DISTILL_TARGET_VALUE")

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
