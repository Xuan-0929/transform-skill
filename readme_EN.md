<div align="center">

# transform-skill

> "Your distilled friend suddenly changed personality overnight?"  
> "New corpus dropped, but you do not want to wipe old style?"

[中文版](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

## What It Does

`transform-skill` is an installable skill package focused on:
1. Optional cold-start distillation from JSON corpus.
2. Update-first evolution of existing skills with controlled weighting.

This repo is optimized for **friend persona evolution**.

## Quick Start

Install with OpenSkills:

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

Prepare corpus folders:

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

Run from chat:

```text
Use distill-from-corpus-path with friend-update:
input=./corpus/incoming/week3.json, persona=laojin, new-corpus-weight=0.2, export both agentskills and codex.
```

## Semantic Command Layer

Primary interface is semantic, not engineering-only CLI.

| Intent | Purpose | LLM required |
|---|---|---|
| `friend-create` | Cold-start create a friend skill | yes |
| `friend-update` | Update existing friend skill | yes |
| `friend-list` | List all friend personas | no |
| `friend-history` | Show history/audit | no |
| `friend-rollback` | Roll back to a version | no |
| `friend-export` | Export to targets | no |
| `friend-correct` | Add correction note | no |
| `friend-doctor` | Runtime diagnostics | no |

Maintainer runner:

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh <intent> [corpus_path] [persona_id]
```

## Update-First Strategy

- Cold-start extraction now uses a **friend object model**.
- Update extraction uses **style anchors** from existing skill.
- Weighted merge (`new-corpus-weight`) controls update aggressiveness.

Weight guide:
- `0.10-0.30`: preserve old persona strongly.
- `0.40-0.60`: balanced blend.
- `0.70-1.00`: aggressive adaptation.

## Multi-Host Installation

See [INSTALL.md](./INSTALL.md) for:
- OpenSkills one-click install (Claude Code/Codex)
- manual Claude Code mount (project/global)
- OpenClaw mount

## Dependency Policy

Optional-first (aligned with colleague/ex style):

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```

- Non-LLM intents work without `claude` runtime.
- LLM intents (`friend-create`, `friend-update`) require local `claude` CLI.
- Auto bootstrap is off by default: `DISTILL_AUTO_BOOTSTRAP=0`.
- Strict auth precheck is off by default: `DISTILL_PRECHECK_CLAUDE_AUTH=0`.

## Acceptance Signals

Check:
- `semantic_intent`
- `workflow_mode` (`agent-led-script-exec`)
- `plan.mode`
- `version`
- `status`
- export paths

