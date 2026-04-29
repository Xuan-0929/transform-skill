# transform.skill（中文说明页）

[中文版入口](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

这份文件和 [README.md](./README.md) 保持同一套快速启动逻辑，方便独立阅读。

## 安装
```bash
git clone https://github.com/Xuan-0929/transform.skill.git
cd transform.skill
```

## 30秒快速启动
1. 准备语料目录
```bash
mkdir -p corpus/bootstrap corpus/incoming
```
2. 登录 Claude
```bash
claude auth login
```
3. 在 Claude Code 里直接说
```text
请使用 distill-from-corpus-path，把 ./corpus/incoming/week2.json 更新到 persona=laojin，新语料权重 0.2
```

## 语料放哪里
- `corpus/bootstrap/`：第一次蒸馏
- `corpus/incoming/`：后续更新

示例路径：
- `./corpus/incoming/week2.json`
- `/Users/you/data/week2.json`

## 直接命令模式（可选）
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh \
./corpus/incoming/week2.json \
laojin
```

## 常见报错
- `Claude CLI is not logged in`：运行 `claude auth login`
- `Error: claude native binary not installed`：执行：
```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```

完整说明、目录与 FAQ 请看 [README.md](./README.md)。
