#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src/persona_distill/"
DST_DIR="$ROOT_DIR/skills/distill-from-corpus-path/runtime/src/persona_distill/"

mkdir -p "$DST_DIR"
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$SRC_DIR" "$DST_DIR"

cat > "$ROOT_DIR/skills/distill-from-corpus-path/runtime/requirements.txt" <<'REQ'
typer>=0.12.3
pydantic>=2.8.2
pyyaml>=6.0.2
REQ

echo "runtime synced to skills/distill-from-corpus-path/runtime"
