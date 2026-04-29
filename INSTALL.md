# transform-skill 安装与运维

更新日期：2026-04-29

## 1. 推荐安装（OpenSkills）

### Claude Code

```bash
npx skills add Xuan-0929/transform-skill \
  --skill transform-skill \
  -a claude-code \
  -y
```

### Codex

```bash
npx skills add Xuan-0929/transform-skill \
  --skill transform-skill \
  -a codex \
  -y
```

### 自检

```bash
npx skills ls -a claude-code
npx skills ls -a codex
```

## 2. 手动挂载（可选）

### Claude Code（项目级）

```bash
mkdir -p .claude/skills
git clone https://github.com/Xuan-0929/transform-skill .claude/skills/transform-skill
```

### Claude Code（全局）

```bash
git clone https://github.com/Xuan-0929/transform-skill ~/.claude/skills/transform-skill
```

### OpenClaw

```bash
git clone https://github.com/Xuan-0929/transform-skill ~/.openclaw/workspace/skills/transform-skill
```

## 3. 运行依赖策略

项目采用 optional-first：

```bash
pip3 install -r skills/transform-skill/runtime/requirements.txt
```

- `create` / `update` 需要当前宿主会话具备模型可用权限。
- `list/history/rollback/export/correct/doctor` 可本地执行。
- 依赖自动自举默认关闭，按需开启：

```bash
DISTILL_AUTO_BOOTSTRAP=1
```

## 4. 主入口与命令层

用户入口：`/transform-skill`（Claude Code）或 `transform-skill`（Codex）

运维脚本入口（可选）：

```bash
./skills/transform-skill/tools/run_transform.sh <action> [options]
```

常用动作：

```bash
# update-first
./skills/transform-skill/tools/run_transform.sh update \
  --input ./corpus/incoming/<new_corpus>.json \
  --friend-id <friend_id> \
  --target-speaker <target_speaker> \
  --new-corpus-weight 0.2 \
  --target both

# cold-start (optional)
./skills/transform-skill/tools/run_transform.sh create \
  --input ./corpus/bootstrap/<seed_corpus>.json \
  --friend-id <friend_id> \
  --target-speaker <target_speaker> \
  --target both

# maintenance
./skills/transform-skill/tools/run_transform.sh list
./skills/transform-skill/tools/run_transform.sh history --friend-id <friend_id>
./skills/transform-skill/tools/run_transform.sh rollback --friend-id <friend_id> --to-version <version>
./skills/transform-skill/tools/run_transform.sh export --friend-id <friend_id> --target both
./skills/transform-skill/tools/run_transform.sh correct --friend-id <friend_id> --correction-text "少一点说教，多一点朋友口吻"
./skills/transform-skill/tools/run_transform.sh doctor
```

## 5. 常见问题

### 5.1 `runtime command is unavailable in this host session`

```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```

### 5.2 `runtime is not authenticated in the current host session`

先确认你在当前 Claude Code/Codex 会话里能正常对话，再重试 `create`/`update`。

### 5.3 Python 依赖缺失

```bash
pip3 install -r skills/transform-skill/runtime/requirements.txt
```

## 6. 兼容入口

旧 skill `distill-from-corpus-path` 继续保留，以兼容历史调用。
新项目统一建议使用 `transform-skill`。
