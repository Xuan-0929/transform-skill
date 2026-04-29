<div align="center">

# transform-skill

> 「蒸留した友だち人格が急に変わった？」  
> 「新しいコーパスを入れたいが、元の話し方は残したい？」

[中文版](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

## プロジェクト概要

`transform-skill` は、友だちペルソナの蒸留と継続更新を行うインストール型 skill パッケージです。

利用パターンは 2 つです。
1. JSON コーパスからのコールドスタート生成（任意）。
2. 既存 skill の update-first 更新（推奨）。

## クイックスタート

### 1) skill をインストール

```bash
# Claude Code
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a claude-code -y

# Codex
npx skills add Xuan-0929/transform-skill --skill distill-from-corpus-path -a codex -y
```

### 2) コーパス用フォルダを作成

```bash
mkdir -p corpus/bootstrap corpus/incoming
```

推奨レイアウト:

| 用途 | パス例 |
|---|---|
| 初回生成用 | `corpus/bootstrap/<seed_corpus>.json` |
| 更新用 | `corpus/incoming/<new_corpus>.json` |

`<friend_id>` は固定で使える ID を推奨します（例: `friend-alex`）。

### 3) 会話で直接実行

既存 skill の更新:

```text
distill-from-corpus-path を使って friend-update を実行してください。
input=./corpus/incoming/<new_corpus>.json,
friend_id=<friend_id>,
target_speaker=<target_speaker>,
new-corpus-weight=0.2,
agentskills と codex を export。
```

コールドスタート（任意）:

```text
distill-from-corpus-path を使って friend-create を実行してください。
input=./corpus/bootstrap/<seed_corpus>.json,
friend_id=<friend_id>,
target_speaker=<target_speaker>,
agentskills と codex を export。
```

`<target_speaker>` はコーパス内の話者名と一致させてください（`speaker` / `role` / `author` / `name`、または `話者: 内容` 形式の話者ラベル）。

## 複数人チャットのコーパスについて

複数人の会話ログを使う場合、毎回 1 人の対象話者を固定して蒸留するのが安全です。

推奨手順:
1. コーパス内の対象話者ラベルを確認（例: `Alex`）。
2. create/update 実行時に `target_speaker=Alex` を明示。
3. 以後の更新でも同じ `friend_id` と `target_speaker` を継続使用。

## セマンティックコマンド層

主な操作はセマンティックコマンドです。

- `friend-create`
- `friend-update`
- `friend-list`
- `friend-history`
- `friend-rollback`
- `friend-export`
- `friend-correct`
- `friend-doctor`

メンテナ向け実行スクリプト（任意）:

```bash
./skills/distill-from-corpus-path/scripts/run_friend_command.sh <intent> [corpus_path] [friend_id] [target_speaker]
```

## Update-First 戦略

- 初回生成は friend object model で抽出。
- 更新時は既存 skill の style anchors を反映。
- `new-corpus-weight` で更新強度を制御。

目安:
- `0.10-0.30`: 既存人格を強く保持
- `0.40-0.60`: バランス更新
- `0.70-1.00`: 強い更新

## 依存ポリシー

optional-first 方針:

```bash
pip3 install -r skills/distill-from-corpus-path/runtime/requirements.txt
```

- 非 LLM 系コマンドは `claude` runtime なしで実行可能。
- `friend-create` / `friend-update` のみ `claude` CLI が必要。

## マルチホスト導入

詳細は [INSTALL.md](./INSTALL.md):
- OpenSkills ワンクリック導入（Claude Code / Codex）
- Claude Code 手動マウント（project/global）
- OpenClaw マウント

## 検収ポイント

- `semantic_intent`
- `workflow_mode` (`agent-led-script-exec`)
- `plan.mode`
- `version`
- `status`
- export path
