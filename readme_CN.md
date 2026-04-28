# Persona Skill Distill（中文版镜像）

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

本文件是中文版镜像，完整内容以 [README.md](./README.md) 为准（主入口已改为 Skill 模式）。

蒸馏过的朋友突然分手，性情大变？  
兄弟的口头禅又变了，想更新 skill？

Skill 模式快速开始：
```bash
claude auth login

./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /absolute/path/chat.json

DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /absolute/path/new_chat.json your-persona
```

也可以在 Claude Code 对话里直接说：  
`请使用 distill-from-corpus-path，把 /absolute/path/chat.json 蒸馏成 skill`
