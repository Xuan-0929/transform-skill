<div align="center">

# transform-skill

> "蒸馏过的朋友突然分手，性情大变？"  
> "兄弟的口头禅又变了，想更新 skill？"

[中文版入口](./README.md) · [中文说明页](./readme_CN.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

[![GitHub stars](https://img.shields.io/github/stars/Xuan-0929/transform-skill?style=for-the-badge&logo=github)](https://github.com/Xuan-0929/transform-skill/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/Xuan-0929/transform-skill?style=for-the-badge&logo=github)](https://github.com/Xuan-0929/transform-skill/commits/main)
[![Claude Code Skill](https://img.shields.io/badge/Claude_Code-Skill-blueviolet?style=for-the-badge)](https://claude.ai/code)
[![Codex Skill](https://img.shields.io/badge/Codex-Skill-black?style=for-the-badge)](https://openai.com/)
[![Mode](https://img.shields.io/badge/Mode-Update--First-00A86B?style=for-the-badge)](#更新优先策略)

</div>

---

## 这项目做什么

`transform-skill` 是一个可安装的 skill 项目，用来把聊天语料蒸馏成“朋友型人格”，并持续更新。

它有两条路径：
1. **冷启动（可选）**：从 0 开始蒸馏朋友人格。
2. **更新优先（推荐）**：用新语料迭代已有人格，尽量保留原有风格。

---

## 快速导航

- [30 秒快速开始](#30-秒快速开始)
- [用户语义命令层](#用户语义命令层)
- [更新优先策略](#更新优先策略)
- [多 Host 安装](#多-host-安装)
- [运行依赖策略](#运行依赖策略)
- [运维与验收](#运维与验收)

---

## 30 秒快速开始

### 1) 一键安装 skill（推荐）

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

### 2) 准备语料目录与文件

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

推荐放置方式：

| 用途 | 路径示例 | 说明 |
|---|---|---|
| 冷启动语料 | `corpus/bootstrap/<seed_corpus>.json` | 首次生成人格使用 |
| 更新语料 | `corpus/incoming/<new_corpus>.json` | 给已有人格做增量更新 |

`<friend_id>` 建议使用英文短横线风格（例如：`friend-alex`）。

### 3) 在 Claude Code / Codex 会话里直接下达任务

更新已有 skill（推荐主路径）：

```text
请使用 distill-from-corpus-path，执行 friend-update：
语料路径 ./corpus/incoming/<new_corpus>.json，目标 friend_id=<friend_id>，
目标说话人=<target_speaker>，新语料权重 0.2，并导出 agentskills 和 codex。
```

冷启动（可选）：

```text
请使用 distill-from-corpus-path，执行 friend-create：
语料路径 ./corpus/bootstrap/<seed_corpus>.json，目标 friend_id=<friend_id>，
目标说话人=<target_speaker>，并导出 agentskills 和 codex。
```

`<target_speaker>` 必须与语料里的说话人字段一致（如 JSON 的 `speaker` / `role` / `author` / `name`，或文本格式里的“说话人: 内容”前缀）。

---

## 多人语料如何指定蒸馏对象

多人聊天语料时，建议每次明确指定一个 `target_speaker`，避免模型混合多个人的表达习惯。

推荐流程：
1. 先确认语料里目标用户的说话人名称（如 `Alex`）。
2. 执行 `friend-create` 或 `friend-update` 时显式带上 `target_speaker=Alex`。
3. 后续更新同一人格时继续使用同一个 `friend_id` 与 `target_speaker`。

---

## 用户语义命令层

主入口是语义命令，而不是工程命令。

| 语义命令 | 作用 | 是否需要 LLM |
|---|---|---|
| `friend-create` | 从 JSON 冷启动创建人格 | 是 |
| `friend-update` | 用新语料更新已有人格 | 是 |
| `friend-list` | 列出现有人格 | 否 |
| `friend-history` | 查看版本和审计历史 | 否 |
| `friend-rollback` | 回滚到指定版本 | 否 |
| `friend-export` | 导出到 agentskills/codex | 否 |
| `friend-correct` | 追加纠偏说明（Correction 层） | 否 |
| `friend-doctor` | 查看运行时诊断信息 | 否 |

脚本运维入口（可选）：

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh <intent> [corpus_path] [friend_id] [target_speaker]
```

示例：

```bash
# 列出现有人格
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-list

# 查看某个人格历史
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-history "" <friend_id>

# 回滚到某个版本
DISTILL_TO_VERSION=<version> ./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-rollback "" <friend_id>

# 用多人语料更新指定用户
./skills/distill-from-corpus-path/scripts/run_friend_command.sh friend-update ./corpus/incoming/<new_corpus>.json <friend_id> <target_speaker>
```

---

## 更新优先策略

### 权重建议

| `new-corpus-weight` | 适合场景 | 结果倾向 |
|---|---|---|
| `0.10 - 0.30` | 只想轻微调口吻 | 强保留旧人格 |
| `0.40 - 0.60` | 常规迭代更新 | 新旧平衡融合 |
| `0.70 - 1.00` | 人设确实变化很大 | 快速吸收新特征 |

### 风格保持机制

- 冷启动：按“朋友对象模型”抽取人格。
- 更新：先读取已有 skill 风格锚点（style anchors），再融合新语料。
- 最终：由 `new-corpus-weight` 控制更新幅度，降低人格漂移风险。

---

## 多 Host 安装

完整安装与运维手册见 [INSTALL.md](./INSTALL.md)。

支持：
- OpenSkills（Claude Code / Codex）
- Claude Code 手动挂载（项目级 / 全局）
- OpenClaw 手动挂载

---

## 运行依赖策略

项目采用 optional-first 策略：

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```

- `friend-list/history/rollback/export/correct` 可在无 LLM 场景执行。
- `friend-create/update` 才需要本机 `claude` CLI。
- 自动依赖自举默认关闭，按需开启：

```bash
DISTILL_AUTO_BOOTSTRAP=1
```

---

## 运维与验收

一次成功执行建议检查这些字段：

- `semantic_intent`
- `workflow_mode`（应为 `agent-led-script-exec`）
- `plan.mode`（`update` 或 `cold_start`）
- `version`
- `status`（`stable` / `quarantined`）
- `export.exports.agentskills`
- `export.exports.codex`

---

## 常见问题

### `friend_id` 是什么

`friend_id` 是你给人格起的唯一标识，用来更新、导出、回滚同一个人格。建议使用英文短横线风格，例如 `friend-alex`。

### `target_speaker` 是什么

`target_speaker` 是语料中你要蒸馏的固定用户名称。它应与语料内说话人字段完全一致（区分大小写和空格）。

### 必须手动写 `friend_id` 吗

不是必须。若不显式提供，系统可从语料文件名自动派生一个 id。生产环境推荐显式指定，便于团队协作。

### 为什么目前只支持 JSON

这是当前版本的边界设计：先把交互入口、更新稳定性和生态安装链路做到可靠，再扩展更多数据接入方式。
