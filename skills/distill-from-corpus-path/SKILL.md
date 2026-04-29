---
name: distill-from-corpus-path
description: Use when the user is already on the legacy distill-from-corpus-path entry and needs backward-compatible access to friend semantic commands or migration guidance to /transform-skill.
argument-hint: "[legacy-friend-command-or-corpus-path]"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# distill-from-corpus-path (Legacy Compatibility)

## Positioning

This skill is kept for backward compatibility.

Primary public entry is now:
- `/transform-skill` (Claude Code)
- `transform-skill` (Codex skill call)

If users start from this legacy skill, continue serving them without breaking old flows.

## Legacy Semantic Command Layer

Supported intents remain unchanged:

- `friend-create`
- `friend-update`
- `friend-list`
- `friend-history`
- `friend-rollback`
- `friend-export`
- `friend-correct`
- `friend-doctor`

## Legacy Runner

```bash
./scripts/run_friend_command.sh <intent> [corpus_path] [friend_id] [target_speaker]
```

Examples:

```bash
./scripts/run_friend_command.sh friend-update ./corpus/incoming/<new_corpus>.json <friend_id> <target_speaker>
./scripts/run_friend_command.sh friend-history "" <friend_id>
```

## Migration Guidance (Recommended)

When appropriate, suggest moving to `/transform-skill` for:
- unified slash-style entry
- prompt + tools orchestration layer
- update-first productized flow

## Runtime Notes

- Base requirement: Python 3.10+.
- `friend-create` / `friend-update` require active model access in current host session.
- Optional dependency bootstrap via:
  - `DISTILL_AUTO_BOOTSTRAP=1`

## Output Contract

Return JSON and highlight:
- `semantic_intent`
- `persona`
- `version`
- `status`
- `workflow_mode`
- export paths when present
