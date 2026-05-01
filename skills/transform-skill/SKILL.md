---
name: transform-skill
description: Use when the user wants to update an existing friend skill with new corpus while preserving style, or run cold-start and maintenance flows from the /transform-skill entrypoint in Claude Code or Codex.
argument-hint: "[task-or-corpus-path]"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# transform-skill

## Unified Entry

Primary entry is `/transform-skill`.

Trigger this skill when the user asks to:
- update an existing friend skill with new corpus
- cold-start distill a new friend skill
- inspect, rollback, export, or correct existing skill versions
- keep old personality while absorbing new language habits

## Product Positioning

- Default path is **update-first**.
- Cold-start is an optional branch.
- Multi-speaker corpus is supported with explicit `target_speaker`.
- Runtime remains deterministic and testable; conversation layer is prompt-guided.

## Conversation Orchestration (Prompt + Tools)

Always orchestrate in this order:

1. Read `prompts/entry-intake.md` and classify intent.
2. If user intent is update, read `prompts/update-playbook.md` and decide update params.
3. If user intent is cold-start, read `prompts/coldstart-playbook.md`.
4. If user intent is maintenance, read `prompts/ops-playbook.md`.
5. Execute using tools layer (`tools/run_transform.sh`).
6. Return both raw JSON result and short user-facing summary.

## Action Map

Use these semantic actions with tools:

| User intent | Action | LLM needed |
|---|---|---|
| Update existing friend | `update` | yes |
| Cold-start create | `create` | yes |
| List friends | `list` | no |
| Show history | `history` | no |
| Rollback version | `rollback` | no |
| Export current/target version | `export` | no |
| Add correction layer | `correct` | no |
| Runtime guidance | `doctor` | no |

## Tool Layer

Canonical executor:

```bash
./tools/run_transform.sh <action> [options]
```


Common options:

- `--input <path>`: corpus file path
- `--friend-id <id>`: stable persona id (recommended)
- `--target-speaker <speaker>`: fixed target in multi-speaker corpus
- `--new-corpus-weight <0.0-1.0>`: update intensity
- `--target <agentskills|codex|both|none>`: export target

Examples:

```bash
# update-first (recommended)
./tools/run_transform.sh update \
  --input ./corpus/incoming/<new_corpus>.json \
  --friend-id <friend_id> \
  --target-speaker <target_speaker> \
  --new-corpus-weight 0.2 \
  --target both

# cold-start (optional)
./tools/run_transform.sh create \
  --input ./corpus/bootstrap/<seed_corpus>.json \
  --friend-id <friend_id> \
  --target-speaker <target_speaker> \
  --target both

# maintenance
./tools/run_transform.sh list
./tools/run_transform.sh history --friend-id <friend_id>
./tools/run_transform.sh rollback --friend-id <friend_id> --to-version <version>
./tools/run_transform.sh export --friend-id <friend_id> --target both
./tools/run_transform.sh correct --friend-id <friend_id> --correction-text "少一点说教，多一点朋友口吻"

```

## MUST Rules

- MUST default to `update` when the user asks for evolution without explicit cold-start intent.
- MUST require `target_speaker` when corpus has multiple speakers.
- MUST keep `friend_id` stable across updates for the same person.
- MUST report `new-corpus-weight` explicitly in summaries for update tasks.
- MUST NOT silently switch `update` to `create` for existing personas.

## Output Contract

Return JSON from tool execution and highlight these fields:

- `semantic_intent`
- `persona`
- `version`
- `status`
- `requested_mode`
- `workflow_mode`
- export paths when available

## Compatibility Note

Legacy skill `distill-from-corpus-path` remains available for backward compatibility.
For new usage, `/transform-skill` is the primary entry.
