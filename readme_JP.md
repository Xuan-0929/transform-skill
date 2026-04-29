<div align="center">

# transform-skill

> 「蒸留した友だち人格が急に変わった？」  
> 「新しいコーパスを入れたいが、既存スタイルは壊したくない？」

[中文版](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

## 概要

`transform-skill` はインストール可能な skill パッケージです。

目的は 2 つです。
1. JSON コーパスからのコールドスタート蒸留（任意）。
2. 既存 skill を update-first で継続進化。

本バージョンは **友だちペルソナ更新** を中心に最適化しています。

## クイックスタート

OpenSkills で導入:

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

コーパス用フォルダ:

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

会話で実行:

```text
distill-from-corpus-path を使って friend-update を実行してください。
input=./corpus/incoming/week3.json, persona=laojin, new-corpus-weight=0.2, agentskills と codex を export。
```

## ユーザー意味コマンド層

エンジニア向け CLI より先に、意味コマンドを使います。

| Intent | 用途 | LLM 必須 |
|---|---|---|
| `friend-create` | コールドスタート作成 | はい |
| `friend-update` | 既存 skill 更新 | はい |
| `friend-list` | 一覧表示 | いいえ |
| `friend-history` | 履歴表示 | いいえ |
| `friend-rollback` | バージョン巻き戻し | いいえ |
| `friend-export` | export | いいえ |
| `friend-correct` | 補正メモ追加 | いいえ |
| `friend-doctor` | 実行環境診断 | いいえ |

メンテナ実行スクリプト:

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh <intent> [corpus_path] [persona_id]
```

## Update-First 戦略

- コールドスタートは **friend object model** で抽出。
- 更新時は既存 skill の **style anchors** を注入。
- `new-corpus-weight` で変化量を制御。

目安:
- `0.10-0.30`: 既存人格を強く保持
- `0.40-0.60`: バランス更新
- `0.70-1.00`: 強い更新

## マルチホスト導入

詳細は [INSTALL.md](./INSTALL.md) を参照:
- OpenSkills（Claude Code/Codex）
- Claude Code 手動マウント（project/global）
- OpenClaw マウント

## 依存ポリシー

同事/前任スタイルと同様に optional-first:

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```

- `friend-list/history/rollback/export/correct` は LLM なしで実行可能。
- `friend-create/update` のみ `claude` CLI が必要。
- 自動ブートストラップは既定で OFF。
- 厳格 auth 事前チェックも既定で OFF。

## 検収ポイント

- `semantic_intent`
- `workflow_mode`
- `plan.mode`
- `version`
- `status`
- export path

