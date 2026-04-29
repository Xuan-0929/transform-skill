# transform-skill

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

Distilled friend changed overnight after a breakup?
Your buddy got new catchphrases and now the skill feels outdated?

`transform-skill` is update-first:
- Primary: update an existing skill with new corpus
- Optional: cold-start distillation from scratch

## Install
```bash
git clone https://github.com/Xuan-0929/transform-skill.git
cd transform-skill
```

Optional (if you work across folders often):
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform-skill
```

## Quickstart (Nuwa / colleague.skill style)
All `<...>` values below are placeholders. Replace them with your actual values.

### 1) Prepare corpus folders
```bash
mkdir -p corpus/bootstrap corpus/incoming
```

Recommended:
- `corpus/bootstrap/`: first-time seed corpus
- `corpus/incoming/`: incremental update corpus

### 2) Login Claude runtime (once)
```bash
claude auth login
```

### 3) Tell Claude Code directly (recommended)
```text
Use distill-from-corpus-path to update persona=<your-persona-id> with ./corpus/incoming/<new-corpus-file>.json and new-corpus-weight=0.2
```

Optional cold-start:
```text
Use distill-from-corpus-path to cold-start persona=<your-persona-id> from ./corpus/bootstrap/<bootstrap-corpus-file>.json
```

### 4) Direct command mode (optional)
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh \
./corpus/incoming/<new-corpus-file>.json \
<your-persona-id>
```

## Output locations
- Version skill: `.distill/personas/<persona>/versions/<version>/skill/`
- Agent Skills export: `.distill/personas/<persona>/exports/<version>/agentskills/`
- Codex export: `.distill/personas/<persona>/exports/<version>/codex/`

## Weight guide
- `0.1-0.3`: conservative, preserve old persona
- `0.4-0.6`: balanced blend
- `0.7-1.0`: stronger adoption of new traits

## Common errors
- `Claude CLI not found`: install Claude Code CLI first
- `Claude CLI is not logged in`: run `claude auth login`
- `Error: claude native binary not installed`: reinstall CLI or run native installer:
```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```
- `Cannot locate persona-distill project root`: run at repo root or set:
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform-skill
```
