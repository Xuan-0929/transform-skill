# transform.skill

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

Your distilled buddy got dumped and now talks like a different person?  
Your bro picked up new catchphrases and you want to refresh the skill?

Welcome to `transform.skill`: the core path is not "build from zero every time", but "continuously update an existing skill with new corpus without destroying persona continuity."

## What this project does
- Incrementally update an existing skill (primary path)
- Distill from scratch (optional path)
- Control how much the new corpus influences persona (`new-corpus-weight`)
- Export artifacts for Agent Skills / Codex consumers
- Single runtime path (no provider switching)

## First things first
Yes, this is a **real skill-style project**, not just Python scripts.

How to tell:
- Dedicated skill contract: `skills/distill-from-corpus-path/SKILL.md`
- Skill entry runner: `skills/distill-from-corpus-path/scripts/run_distill_from_path.sh`
- Runtime precheck for Claude CLI (`claude --version`, `claude auth status`)
- Accepts corpus path as first input and runs end-to-end distillation

## Skill mode quickstart (recommended)
### 0) Prerequisite
```bash
claude auth login
```

### 1) Primary path: update existing skill
Examples:
- `Use distill-from-corpus-path to update persona=laojin with /absolute/path/new_chat.json, new-corpus-weight=0.2`
- `Use distill-from-corpus-path and continue evolving my existing skill from /absolute/path/week2.json`

### 2) Or run the skill entry script (update mode)
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /absolute/path/new_chat.json laojin
```

Optional:
- Cold start from scratch: `./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /path/bootstrap_chat.json laojin`
- With speaker filter: `./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /path/new_chat.json laojin Ajin`

## Weight guide
- `0.1-0.3`: conservative, preserve old persona
- `0.4-0.6`: balanced blend
- `0.7-1.0`: aggressive adoption of new traits

In short: lower = safer, higher = bolder.

## Developer mode (optional)
If you are maintaining/extending this project, use Python commands:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

PYTHONPATH=src python -m persona_distill doctor
PYTHONPATH=src python -m persona_distill run --input ./your_corpus.json --target both
```

## FAQ
### What is the real focus of this project?
Continuous **skill evolution by new corpus updates**.  
Cold-start distillation is available, but secondary.

### Why do Python commands still exist if this is a skill project?
Two audiences:
- Skill users: path in, skill out
- Maintainers: local debugging and development workflows
