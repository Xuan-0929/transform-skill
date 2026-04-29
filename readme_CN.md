<div align="center">

# transform-skill（中文）

> 「蒸馏过的人设突然变味？\
> 新语料来了，又怕一更新就把老人格冲掉？」

[中文版入口](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

<br/>

[![GitHub stars](https://img.shields.io/github/stars/Xuan-0929/transform-skill?style=for-the-badge&logo=github)](https://github.com/Xuan-0929/transform-skill/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/Xuan-0929/transform-skill?style=for-the-badge&logo=github)](https://github.com/Xuan-0929/transform-skill/commits/main)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

[![Claude Code Skill](https://img.shields.io/badge/Claude_Code-Skill-blueviolet?style=for-the-badge)](https://claude.ai/code)
[![Codex Skill](https://img.shields.io/badge/Codex-Skill-black?style=for-the-badge)](https://openai.com/)
[![Update First](https://img.shields.io/badge/Mode-Update--First-00A86B?style=for-the-badge)](#更新优先策略)

</div>

---

## OpenSkills 一键安装

先看可安装技能：

```bash
npx skills add Xuan-0929/transform-skill --list
```

安装到 Claude Code：

```bash
npx skills add Xuan-0929/transform-skill \
  --skill distill-from-corpus-path \
  -a claude-code \
  -y
```

安装到 Codex：

```bash
npx skills add Xuan-0929/transform-skill \
  --skill distill-from-corpus-path \
  -a codex \
  -y
```

说明：
- skill 内置运行时在 `skills/distill-from-corpus-path/runtime`
- 默认自动自举依赖（`DISTILL_AUTO_BOOTSTRAP=0` 可关闭）
- 蒸馏执行仍依赖本机 `claude` CLI（在 Codex 中触发也一样，需要先 `claude auth login`）

### OpenSkills 格式对齐说明

这个仓库不是“只有提示词”的壳子，而是完整可安装 skill 包：

- skill 入口：`skills/distill-from-corpus-path/SKILL.md`
- 安装发现：`npx skills add <repo> --list` 可列出技能
- 运行时同捆：`runtime/src/persona_distill` 随 skill 一起安装
- 脚本自定位：支持 `DISTILL_PROJECT_ROOT` / skill 目录双路径解析

---

## 30 秒快速启动

按 OpenSkills 习惯：先装载 skill，再在会话里直接发任务。以下 `<...>` 是占位符。

### 1) 装载到 Claude Code / Codex（只做一次）

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

### 2) 确认已装载并登录运行时

```bash
npx skills ls -a claude-code
npx skills ls -a codex
claude auth login
```

### 3) 准备语料路径

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

- `corpus/incoming/<new-corpus-file>.json`：更新已有 persona
- `corpus/bootstrap/<bootstrap-corpus-file>.json`：从 0 冷启动

### 4) 在会话里直接下任务（推荐）

更新：

```text
请使用 distill-from-corpus-path，把 ./corpus/incoming/<new-corpus-file>.json 更新到 persona=<your-persona-id>，新语料权重 0.2，并导出 agentskills 和 codex。
```

冷启动（可选）：

```text
请使用 distill-from-corpus-path，用 ./corpus/bootstrap/<bootstrap-corpus-file>.json 冷启动 persona=<your-persona-id>，并导出 agentskills 和 codex。
```

### 5) 验收看这几个字段

- `workflow_mode`
- `plan.mode`
- `version`
- `status`
- `export.exports.agentskills`
- `export.exports.codex`

---

## 核心工作流图

```mermaid
flowchart TD
    A[输入新语料\ncorpus/incoming/*.json] --> B[Agent Orchestrator\ndistill orchestrate]
    B --> C[脚本执行层]
    C --> D{persona 是否已存在?}
    D -- 是 --> E[Update 模式\n融合旧人格 + 新语料]
    D -- 否 --> F[Cold Start 模式\n从 0 蒸馏]

    E --> G[权重融合\nnew-corpus-weight]
    F --> H[生成初版人格]

    G --> I[评估与门禁]
    H --> I

    I --> J{通过?}
    J -- 是 --> K[stable 版本]
    J -- 否 --> L[quarantined 版本]

    K --> M[导出 AgentSkills]
    K --> N[导出 Codex]
    L --> O[保留版本 + 回滚可用]
```

---

## 更新优先策略

| `new-corpus-weight` | 适合场景 | 结果倾向 |
|---|---|---|
| `0.10 - 0.30` | 轻微微调 | 旧人格强保留 |
| `0.40 - 0.60` | 常规迭代 | 新旧平衡融合 |
| `0.70 - 1.00` | 阶段变化 | 快速吸收新特征 |

---

## 输出路径

- 版本技能：`.distill/personas/<persona>/versions/<version>/skill/`
- Agent Skills 导出：`.distill/personas/<persona>/exports/<version>/agentskills/`
- Codex 导出：`.distill/personas/<persona>/exports/<version>/codex/`

---

## 常见报错

- `Claude CLI is not logged in`
```bash
claude auth login
```

- `Error: claude native binary not installed`
```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```

- 找不到运行时根目录
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform-skill
```
