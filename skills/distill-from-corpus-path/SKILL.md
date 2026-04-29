---
name: distill-from-corpus-path
description: Use when the user wants to evolve a friend-style skill from JSON corpus paths with update-first behavior, semantic maintenance commands, and optional cold-start creation.
argument-hint: "[friend-command-or-corpus-path]"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# transform-skill Operator

## Trigger

Start this skill when the user asks to:
- distill from a JSON corpus path
- update an existing friend skill with new corpus
- manage versions (list/history/rollback/export/correction)
- keep old style while absorbing new corpus

## Runtime Positioning

- This skill is **agent-led + script-executed**.
- Data ingestion stays JSON-first (no extra connectors in this skill).
- Primary operation layer is **semantic friend commands** (not engineering-only CLI).

## Semantic Command Layer

Use `distill friend --intent <intent>` as the canonical interface.

| Intent | Meaning | LLM needed |
|---|---|---|
| `friend-create` | Cold-start create from corpus | yes |
| `friend-update` | Update existing skill from new corpus | yes |
| `friend-list` | List all distilled friends | no |
| `friend-history` | Show version/audit history | no |
| `friend-rollback` | Roll back to target version | no |
| `friend-export` | Export current/target version | no |
| `friend-correct` | Add correction layer note | no |
| `friend-doctor` | Show runtime and command guidance | no |

## Primary Runner

- `scripts/run_friend_command.sh`
  - Usage: `run_friend_command.sh <intent> [corpus_path] [persona_id]`
  - Examples:
    - `run_friend_command.sh friend-create ./corpus/bootstrap/friend.json laojin`
    - `run_friend_command.sh friend-update ./corpus/incoming/week3.json laojin`
    - `run_friend_command.sh friend-history "" laojin`

## Compatibility Runners (Maintainer)

- `scripts/run_agent_orchestrated.sh` (agent-led engineering path)
- `scripts/run_distill_from_path.sh` (legacy one-shot path)

## Dependency Strategy (Optional-First)

- Base requirement: Python 3.10+, local `claude` CLI for LLM intents.
- Optional deps install:
  - `pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt`
- Auto bootstrap is **off by default**; enable only when needed:
  - `DISTILL_AUTO_BOOTSTRAP=1`
- Auth precheck is **off by default**; enable for strict ops:
  - `DISTILL_PRECHECK_CLAUDE_AUTH=1`

## Execution Rules

1. Resolve corpus path and persona id.
2. Prefer semantic intent flow first.
3. If intent is `friend-update`, keep update-first defaults with controllable `new-corpus-weight`.
4. If intent is `friend-create`, cold-start with friend-oriented object model.
5. Return raw JSON plus key fields:
   - `semantic_intent`, `persona`, `version`, `status`, `workflow_mode`, `plan`, `stages`
   - export paths when present.

## User Invocation Examples

- `请使用 distill-from-corpus-path，执行 friend-update：语料 ./corpus/incoming/new.json，persona=laojin，新语料权重 0.2，并导出到 agentskills + codex。`
- `请使用 distill-from-corpus-path，执行 friend-create：语料 ./corpus/bootstrap/friend_seed.json，persona=laojin。`
- `请使用 distill-from-corpus-path，执行 friend-history，persona=laojin。`

