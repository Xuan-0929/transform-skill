---
name: distill-from-corpus-path
description: Distill conversation corpora into a complete skill package by providing only a corpus file path. Use this skill when the user wants to run persona distillation in Claude Code or Codex with minimal steps, including no manual init/ingest/build/export sequence and no model-provider switching.
---

# Distill From Corpus Path

## Workflow

1. Confirm the corpus file path exists and is readable.
2. Resolve project root:
   - Prefer `DISTILL_PROJECT_ROOT` when set.
   - Otherwise run from the current directory if it contains `pyproject.toml` and `src/persona_distill`.
3. Run one-shot distillation:
   - `distill run --input <path> --target both`
4. Return the generated version, status, and exported output paths from CLI JSON.

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

## Output Requirements

1. Print raw JSON from `distill run`.
2. Surface these fields in the response:
   - `persona`
   - `version`
   - `status`
   - `output_dir`
   - `export.exports.agentskills` and `export.exports.codex` when present
3. If validation or gates fail, still report the new version and quarantine status.
