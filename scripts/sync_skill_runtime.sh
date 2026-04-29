#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src/persona_distill/"
DISTILL_DST_DIR="$ROOT_DIR/skills/distill-from-corpus-path/runtime/src/persona_distill/"
TRANSFORM_DST_DIR="$ROOT_DIR/skills/transform-skill/runtime/src/persona_distill/"

sync_runtime() {
  local dst_dir="$1"
  mkdir -p "$dst_dir"
  rsync -a --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$SRC_DIR" "$dst_dir"
}

sync_runtime "$DISTILL_DST_DIR"
sync_runtime "$TRANSFORM_DST_DIR"

for req in \
  "$ROOT_DIR/skills/distill-from-corpus-path/runtime/requirements.txt" \
  "$ROOT_DIR/skills/transform-skill/runtime/requirements.txt"; do
  cat > "$req" <<'REQ'
typer>=0.12.3
pydantic>=2.8.2
pyyaml>=6.0.2
REQ
done

echo "runtime synced to:"
echo "- skills/distill-from-corpus-path/runtime"
echo "- skills/transform-skill/runtime"
