<div align="center">

# transform-skill

> "Your distilled friend suddenly changed personality overnight?"  
> "New corpus arrived, but you want to keep the old voice?"

[中文版](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

## What It Is

`transform-skill` is an installable skill package for friend-persona distillation and evolution.

It supports two paths:
1. Optional cold-start creation from JSON corpus.
2. Update-first evolution of an existing skill (recommended).

## Quick Start

### 1) Install the skill

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

### 2) Prepare corpus folders

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

Recommended layout:

| Purpose | Path example |
|---|---|
| Cold start corpus | `corpus/bootstrap/<seed_corpus>.json` |
| Update corpus | `corpus/incoming/<new_corpus>.json` |

Use a stable `<friend_id>` (for example: `friend-alex`).

### 3) Run directly from chat

Update existing skill:

```text
Use distill-from-corpus-path and run friend-update:
input=./corpus/incoming/<new_corpus>.json,
friend_id=<friend_id>,
target_speaker=<target_speaker>,
new-corpus-weight=0.2,
export both agentskills and codex.
```

Cold start (optional):

```text
Use distill-from-corpus-path and run friend-create:
input=./corpus/bootstrap/<seed_corpus>.json,
friend_id=<friend_id>,
target_speaker=<target_speaker>,
export both agentskills and codex.
```

`<target_speaker>` should match the speaker name in your corpus fields (`speaker`, `role`, `author`, `name`, or text prefix like `Speaker: content`).

## Multi-Speaker Corpus: Select One Person

If your chat corpus includes multiple people, always fix a single target speaker for each distillation run.

Recommended pattern:
1. Find the exact speaker label in corpus (for example `Alex`).
2. Pass `target_speaker=Alex` in create/update runs.
3. Keep using the same `friend_id` + `target_speaker` pair for future updates.

## Semantic Command Layer

Primary interface is semantic commands:

- `friend-create`
- `friend-update`
- `friend-list`
- `friend-history`
- `friend-rollback`
- `friend-export`
- `friend-correct`
- `friend-doctor`

Maintainer runner (optional):

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh <intent> [corpus_path] [friend_id] [target_speaker]
```

## Update-First Strategy

- Cold start uses a friend-focused object model.
- Update path injects style anchors from the existing skill.
- `new-corpus-weight` controls how aggressively new corpus reshapes behavior.

Weight guide:
- `0.10-0.30`: conservative update, strong preservation.
- `0.40-0.60`: balanced blend.
- `0.70-1.00`: aggressive adaptation.

## Dependency Policy

Optional-first runtime policy:

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```

- Non-LLM intents can run without `claude` runtime.
- `friend-create` / `friend-update` require local `claude` CLI.

## Multi-Host Install

See [INSTALL.md](./INSTALL.md) for:
- OpenSkills one-click install (Claude Code / Codex)
- manual mount for Claude Code (project/global)
- OpenClaw mount

## Acceptance Signals

Check:
- `semantic_intent`
- `workflow_mode` (`agent-led-script-exec`)
- `plan.mode`
- `version`
- `status`
- export paths
