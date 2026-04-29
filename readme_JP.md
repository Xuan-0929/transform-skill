# transform.skill

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

蒸留した友だち、失恋して急に人格変わった？  
口ぐせが増えて、skill を更新したくなった？

`transform.skill` の主眼は「毎回ゼロから作ること」ではなく、「既存 skill を新しいコーパスで継続更新すること」です。

## できること
- 既存 skill の段階的アップデート（主ルート）
- ゼロから蒸留（オプション）
- `new-corpus-weight` で新語料の影響度を調整
- Agent Skills / Codex 向けに出力
- プロバイダ切替なしの単一路線実行

## 先に結論
はい、これは **skill 形式** です。Python スクリプト集だけではありません。

判断ポイント：
- skill 契約ファイル: `skills/distill-from-corpus-path/SKILL.md`
- skill 実行入口: `skills/distill-from-corpus-path/scripts/run_distill_from_path.sh`
- Claude 実行時プリチェックあり（`claude --version`, `claude auth status`）
- コーパスのパスを渡せば蒸留を一気通貫で実行

## Skill モード クイックスタート（推奨）
### 0) 前提
```bash
claude auth login
```

### 1) 主ルート：既存 skill を更新
例：
- `distill-from-corpus-path を使って /absolute/path/new_chat.json で persona=laojin を更新、weight=0.2`
- `distill-from-corpus-path を使って既存 skill を /absolute/path/week2.json で継続更新して`

### 2) もしくは skill 入口スクリプトを実行（更新モード）
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /absolute/path/new_chat.json laojin
```

オプション：
- コールドスタート（ゼロ蒸留）: `./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /path/bootstrap_chat.json laojin`
- speaker 指定: `./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh /path/new_chat.json laojin Ajin`

## 重みの目安
- `0.1-0.3`: 保守的（旧人格を強く保持）
- `0.4-0.6`: バランス型
- `0.7-1.0`: 新特性を強く反映

一言で言うと、低いほど保守・高いほど攻め。

## 開発者モード（任意）
メンテナ向けのローカル実行：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

PYTHONPATH=src python -m persona_distill doctor
PYTHONPATH=src python -m persona_distill run --input ./your_corpus.json --target both
```

## FAQ
### このプロジェクトの重点は？
重点は **新語料による既存 skill の継続進化** です。  
ゼロ蒸留は補助的な入口です。

### skill なのに Python コマンドが残っているのはなぜ？
対象が2種類あるためです：
- skill 利用者：パスを渡して蒸留するだけ
- 保守者：デバッグ・実装変更・検証のために Python 実行が必要
