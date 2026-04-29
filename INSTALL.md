# transform-skill Multi-Host Install Manual

Last updated: 2026-04-29

## 0. What You Install

- Skill name: `distill-from-corpus-path`
- Primary interface: `friend-*` semantic intents
- Data format: JSON corpus path only (by design)

## 1. OpenSkills (Recommended)

### 1.1 Claude Code

```bash
npx skills add Xuan-0929/transform-skill \
  --skill distill-from-corpus-path \
  -a claude-code \
  -y
```

### 1.2 Codex

```bash
npx skills add Xuan-0929/transform-skill \
  --skill distill-from-corpus-path \
  -a codex \
  -y
```

### 1.3 Verify Install

```bash
npx skills ls -a claude-code
npx skills ls -a codex
```

## 2. Manual Host Mount

### 2.1 Claude Code Local Project

Run from your git project root:

```bash
mkdir -p .claude/skills
git clone https://github.com/Xuan-0929/transform-skill .claude/skills/transform-skill
```

### 2.2 Claude Code Global

```bash
git clone https://github.com/Xuan-0929/transform-skill ~/.claude/skills/transform-skill
```

### 2.3 OpenClaw

```bash
git clone https://github.com/Xuan-0929/transform-skill ~/.openclaw/workspace/skills/transform-skill
```

## 3. Runtime Dependency Strategy

This project follows optional-first dependency policy (same philosophy as colleague/ex):

- Python dependency install is optional but recommended:

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```

- `claude` CLI is only required for LLM intents:
  - `friend-create`
  - `friend-update`

- By default:
  - `DISTILL_AUTO_BOOTSTRAP=0`
  - `DISTILL_PRECHECK_CLAUDE_AUTH=0`

- Turn on auto bootstrap if needed:

```bash
DISTILL_AUTO_BOOTSTRAP=1 ./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-doctor
```

- Turn on strict auth precheck if your ops policy requires it:

```bash
DISTILL_PRECHECK_CLAUDE_AUTH=1 ./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-update ./corpus/incoming/<new_corpus>.json <friend_id> <target_speaker>
```

## 4. First Run (Host-Agnostic)

Create corpus folders:

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

Cold-start:

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh \
  friend-create \
  ./corpus/bootstrap/<seed_corpus>.json \
  <friend_id> \
  <target_speaker>
```

Update:

```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_friend_command.sh \
  friend-update \
  ./corpus/incoming/<new_corpus>.json \
  <friend_id> \
  <target_speaker>
```

## 5. Maintenance Commands

```bash
# list all personas
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-list

# show history
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-history "" <friend_id>

# rollback
DISTILL_TO_VERSION=v0003 \
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-rollback "" <friend_id>

# export
DISTILL_EXPORT_TARGET=both \
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-export "" <friend_id>

# add correction note
DISTILL_CORRECTION_TEXT="少一点说教，多一点兄弟口吻" \
DISTILL_CORRECTION_SECTION=expression_dna \
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-correct "" <friend_id>
```

## 6. Troubleshooting

### `Claude CLI not found`

```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```

### `Claude CLI is not authenticated`

```bash
claude auth login
```

### Python deps missing

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```
