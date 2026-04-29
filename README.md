# transform.skill

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

蒸馏过的朋友突然分手，性情大变？  
兄弟的口头禅又变了，想更新 skill？

欢迎来到 `transform.skill`：它的核心不是“从 0 造一个人格”，而是让你把**新增语料持续注入已有 skill**，稳态进化，不推翻旧人格。

## 这项目能干啥
- 对已有 skill 做增量更新（主路径）
- 从 0 语料蒸馏 skill（可选路径）
- 用 `new-corpus-weight` 控制“新语料话语权”
- 导出为 Agent Skills / Codex 可消费格式
- 单一路径运行：不需要 API Key，不需要 provider 切换

## 先回答你最关心的
是的，这一版是 **skill 形态**，不是“只会跑 python 命令的脚本仓库”。

判定标准：
- 有独立 skill 目录和契约文件：`skills/distill-from-corpus-path/SKILL.md`
- 有 skill 入口脚本：`skills/distill-from-corpus-path/scripts/run_distill_from_path.sh`
- 入口脚本做了 Claude 运行时预检（`claude --version`、`claude auth status`）
- skill 接收“语料路径”作为第一输入，直接跑蒸馏，不要求你手工 `init/ingest/build`

## 项目结构
```text
src/persona_distill/                       # 核心逻辑
skills/distill-from-corpus-path/           # Claude Code / Codex skill入口
a) SKILL.md
b) scripts/run_distill_from_path.sh
```

## Skill模式快速开始（推荐）
### 0) 前置
```bash
claude auth login
```

### 1) 主路径：更新已有 skill（推荐）
示例（自然语言触发 skill）：
- `请使用 distill-from-corpus-path，把 /absolute/path/new_chat.json 更新到 persona=laojin，新语料权重 0.2`
- `请使用 distill-from-corpus-path，用 /absolute/path/week2.json 继续更新现有 skill，保持原人格风格`

### 2) 或者直接调用 skill 入口脚本（更新模式）
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /absolute/path/new_chat.json laojin
```

可选：
- 冷启动（从 0 蒸馏）：`./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /path/chat_bootstrap.json laojin`
- 指定 speaker：`./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /path/new_chat.json laojin 阿金`

## `new-corpus-weight` 怎么选
| 权重 | 适合场景 | 效果 |
|---|---|---|
| `0.1-0.3` | 只想微调口头禅/语气 | 旧人格强保留，变化温和 |
| `0.4-0.6` | 新语料明显增多 | 新旧平衡融合 |
| `0.7-1.0` | 人设确实发生阶段性变化 | 更积极吸收新特征 |

一句话：越小越保守，越大越激进。

## 开发者模式（可选）
如果你要二次开发或本地调试，再使用 Python 命令：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 运行时检查
PYTHONPATH=src python -m persona_distill doctor

# 直接跑 CLI（等价于 skill 底层）
PYTHONPATH=src python -m persona_distill run --input ./your_corpus.json --target both
```

## 常见问题
### 这个项目的重点到底是什么？
重点是“**持续更新已有 skill**”。  
从 0 蒸馏是可选入口，适合第一次建档。

### 我都挂在 Claude Code 了，为什么文档里还有 Python？
因为有两类用户：
- **Skill 使用者**：只关心“给路径就能蒸馏”（上面的 Skill 模式）
- **项目维护者**：需要本地调试、改代码、跑验证（开发者模式）

你要的主入口已经是 Skill 模式，不是 Python。

### 为什么有时候会看到 `status: quarantined`？
通常是语料太少、噪声太多，或评估门禁没过。先补充高质量语料，再重新跑 `run/update`。

### 要不要先手动 `init/ingest/build`？
不用。大多数场景直接 `run` 就够了。

### 我只想更新，不想重建人设
用 `update`，并把 `--new-corpus-weight` 调低（如 `0.2`）。

## 一句话收尾
`transform.skill`：先有一个基线 skill，然后用新语料持续改造它。  
不是重来，而是进化。
