<div align="center">

# transform-skill（中文说明）

[中文版入口 README](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

这是中文说明页。完整内容与最新示例以 [README.md](./README.md) 为准。

## 一屏上手

1. 安装 skill：

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

2. 准备语料目录：

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

3. 会话中直接说：

```text
请使用 distill-from-corpus-path，执行 friend-update：
语料路径 ./corpus/incoming/<new_corpus>.json，目标 friend_id=<friend_id>，
目标说话人=<target_speaker>，新语料权重 0.2，并导出 agentskills 和 codex。
```

`<target_speaker>` 需要与语料里的说话人字段一致（如 `speaker` / `role` / `author` / `name`）。

## 关键概念

- `friend_id`：人格唯一 ID（建议英文短横线，例如 `friend-alex`）。
- `target_speaker`：多用户语料里要蒸馏的固定对象。
- `friend-create`：冷启动创建人格。
- `friend-update`：更新已有人格（推荐主路径）。
- `new-corpus-weight`：控制新语料影响强度。

## 语义命令总览

- `friend-create`
- `friend-update`
- `friend-list`
- `friend-history`
- `friend-rollback`
- `friend-export`
- `friend-correct`
- `friend-doctor`

多人语料建议：
1. 先确认目标用户在语料中的说话人名称。
2. 在 `friend-create` 或 `friend-update` 时显式指定该 `target_speaker`。
3. 后续更新沿用同一个 `friend_id + target_speaker` 组合。

多 Host 安装与运维细节见 [INSTALL.md](./INSTALL.md)。
