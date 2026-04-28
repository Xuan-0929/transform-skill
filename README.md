# Persona Skill Distill

## 中文
蒸馏过的朋友突然分手，性情大变？
兄弟的口头禅又变了，想更新 skill？

这个项目就是干这个的：
- 给一份语料，直接蒸馏成可用 skill
- 再喂新语料，按权重温和更新，不会一把把旧人格掀翻
- 单一路径运行：不需要配置 API Key，不切换 provider

快速开始：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 一步蒸馏
PYTHONPATH=src python -m persona_distill run --input ./your_corpus.json --target both

# 增量更新（new-corpus-weight 越小越保守）
PYTHONPATH=src python -m persona_distill update \
  --persona your-persona \
  --input ./new_corpus.json \
  --new-corpus-weight 0.2
```

Skill 入口脚本（Claude Code / Codex）：
```bash
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh ./your_corpus.json
```

---

## English
Your distilled buddy got dumped and now talks like a different person?
Your bro picked up new catchphrases and you want to refresh the skill?

This repo does exactly that:
- Distill a skill from your corpus
- Update it with new corpus using controllable weight
- Keep old persona signals while allowing gradual change
- Single runtime path, no API-key setup workflow

Quickstart:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

PYTHONPATH=src python -m persona_distill run --input ./your_corpus.json --target both

PYTHONPATH=src python -m persona_distill update \
  --persona your-persona \
  --input ./new_corpus.json \
  --new-corpus-weight 0.2
```

Skill runner (Claude Code / Codex):
```bash
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh ./your_corpus.json
```

---

## 日本語
蒸留した友だち、失恋して急に人格変わった？
口ぐせが増えて、skill を更新したくなった？

このプロジェクトの役目はシンプルです：
- コーパスから skill を蒸留
- 新しいコーパスで重み付き更新
- 元の人格を残しつつ、少しずつ変化を反映
- API キー設定フローなし、単一路線で実行

クイックスタート：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

PYTHONPATH=src python -m persona_distill run --input ./your_corpus.json --target both

PYTHONPATH=src python -m persona_distill update \
  --persona your-persona \
  --input ./new_corpus.json \
  --new-corpus-weight 0.2
```

Skill 実行スクリプト（Claude Code / Codex）：
```bash
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh ./your_corpus.json
```
