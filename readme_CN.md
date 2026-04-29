<div align="center">

# transform-skill（中文索引）

[中文版入口 README](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

本页是中文索引。完整中文文档、快速开始、语义命令、运维策略都在 [README.md](./README.md)。

## 一屏摘要

- 主目标：更新已有 skill，不让新语料推翻旧人格。
- 冷启动：已特化为“朋友对象模型”。
- 更新：基于已有 skill 风格锚点 + `new-corpus-weight` 融合。
- 入口：用户语义命令层（`friend-*`），不是工程 CLI 心智。
- 多 Host：Claude Code / Codex / OpenClaw，详见 [INSTALL.md](./INSTALL.md)。

## 快速命令

```bash
# 安装到 Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# 安装到 Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

```text
请使用 distill-from-corpus-path，执行 friend-update：
语料 ./corpus/incoming/week3.json，persona=laojin，新语料权重 0.2，导出 agentskills + codex。
```

## 运维入口

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh <intent> [corpus_path] [persona_id]
```

语义命令：
- `friend-create`
- `friend-update`
- `friend-list`
- `friend-history`
- `friend-rollback`
- `friend-export`
- `friend-correct`
- `friend-doctor`

