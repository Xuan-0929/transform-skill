---
name: distill-from-corpus-path
description: Update an existing skill with new corpus by only providing a corpus path (update-first), with optional cold-start distillation from scratch. Use this skill when the user wants Claude Code or Codex to evolve persona skills without manual init/ingest/build/export steps.
---

# Distill From Corpus Path

## Workflow

1. Confirm the corpus file path exists and is readable.
2. Confirm Claude Code CLI runtime is ready:
   - `claude --version` works
   - `claude auth status` shows `"loggedIn": true`
3. Resolve project root:
   - Prefer `DISTILL_PROJECT_ROOT` when set.
   - Otherwise run from the current directory if it contains `pyproject.toml` and `src/persona_distill`.
4. Primary path: update existing persona skill with new corpus (update-first):
   - `distill run --input <path> --persona <existing_persona> --new-corpus-weight <0.0-1.0> --target both`
5. Optional path: cold-start distillation when no persona exists yet:
   - `distill run --input <path> --target both`
6. Return the generated version, status, and exported output paths from CLI JSON.

## Command Contract

- Primary runner script: `scripts/run_distill_from_path.sh`
- Required argument: corpus path.
- Optional argument 2: persona id override.
- Optional argument 3: speaker filter.
- Optional env overrides:
  - `DISTILL_PROJECT_ROOT`
  - `DISTILL_EXPORT_TARGET` (default `both`)
  - `DISTILL_FORMAT` (default `auto`)
  - `DISTILL_NEW_CORPUS_WEIGHT` (optional, `0.0-1.0`, lower means stronger persona preservation)
  - `DISTILL_EVAL_SUITE` (optional)
  - `DISTILL_SKIP_CLAUDE_AUTH_CHECK` (optional, test-only; set `1` to skip login precheck)

## Output Requirements

1. Print raw JSON from `distill run`.
2. Surface these fields in the response:
   - `persona`
   - `version`
   - `status`
   - `output_dir`
   - `export.exports.agentskills` and `export.exports.codex` when present
3. If validation or gates fail, still report the new version and quarantine status.
4. Emphasize update-first flow in user-facing explanation; mention cold-start only as optional.

## User Invocation Examples

- `请使用 distill-from-corpus-path，把 /absolute/path/<new-corpus-file>.json 更新到 persona=<your-persona-id>，新语料权重 0.2`
- `请使用 distill-from-corpus-path，用 /absolute/path/<bootstrap-corpus-file>.json 冷启动蒸馏 persona=<your-persona-id>（可选）`
