# transform-skill

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

蒸馏过的朋友突然分手，性情大变？
兄弟的口头禅又变了，想更新 skill？

`transform-skill` 的核心目标是：
- 主路径：用新增语料持续更新已有 skill
- 可选路径：从 0 开始冷启动蒸馏

## 你会得到什么
- 只给语料路径，就能在 Claude Code / Codex 里跑蒸馏
- `new-corpus-weight` 控制新语料权重，避免“新语料一来就推翻旧人格”
- 自动产出 Agent Skills / Codex 可消费的导出目录
- 不需要再配第三方 API key 或切换 provider

## 安装
```bash
git clone https://github.com/Xuan-0929/transform-skill.git
cd transform-skill
```

如果你经常跨目录使用，建议固定项目根目录（可选）：
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform-skill
```

## 快速启动（Nuwa / 同事.skill 风格）
以下示例中的 `<...>` 都是占位符，请替换成你自己的真实值。

### 1) 先放语料
```bash
mkdir -p corpus/bootstrap corpus/incoming
```

推荐放法：
- `corpus/bootstrap/`：第一次建档语料（冷启动）
- `corpus/incoming/`：后续新增语料（更新）

路径支持相对/绝对两种：
- `./corpus/incoming/<new-corpus-file>.json`
- `/absolute/path/<new-corpus-file>.json`

### 2) 登录 Claude（一次）
```bash
claude auth login
```

### 3) 在 Claude Code 里直接说（推荐）
```text
请使用 distill-from-corpus-path，把 ./corpus/incoming/<new-corpus-file>.json 更新到 persona=<your-persona-id>，新语料权重 0.2
```

可选：
```text
请使用 distill-from-corpus-path，用 ./corpus/bootstrap/<bootstrap-corpus-file>.json 冷启动 persona=<your-persona-id>
```

### 4) 你想直接敲命令也可以
更新已有 skill（推荐）：
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh \
./corpus/incoming/<new-corpus-file>.json \
<your-persona-id>
```

从 0 冷启动（可选）：
```bash
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh \
./corpus/bootstrap/<bootstrap-corpus-file>.json \
<your-persona-id>
```

指定 speaker（可选）：
```bash
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh \
./corpus/incoming/<new-corpus-file>.json \
<your-persona-id> \
<speaker-name>
```

## 结果文件在哪
每次运行后，重点看这几个目录：
- 版本技能：`.distill/personas/<persona>/versions/<version>/skill/`
- Agent Skills 导出：`.distill/personas/<persona>/exports/<version>/agentskills/`
- Codex 导出：`.distill/personas/<persona>/exports/<version>/codex/`

## `new-corpus-weight` 怎么选
- `0.1-0.3`：小步微调，尽量保留旧人格
- `0.4-0.6`：新旧平衡融合
- `0.7-1.0`：积极吸收新语料特征

一句话：值越小越稳，值越大变化越明显。

## 常见报错
- `Claude CLI not found`：先安装 Claude Code CLI
- `Claude CLI is not logged in`：运行 `claude auth login`
- `Error: claude native binary not installed`：重装 CLI 或手动补装 native binary：
```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```
- `Cannot locate persona-distill project root`：你不在仓库根目录，或者要先设置：
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform-skill
```

## 开发者模式（仅在你要改代码时）
如果你只是使用 skill，可忽略这段。需要改代码时再用：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
PYTHONPATH=src python -m persona_distill doctor
```

## 一句话结尾
`transform-skill` 不是“每次重来”，而是“先有基线，再用新语料持续进化”。
