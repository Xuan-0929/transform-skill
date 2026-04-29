# transform.skill

[中文版](./README.md) | [English](./readme_EN.md) | [日本語](./readme_JP.md)

蒸留した友だち、失恋して急に人格が変わった？
口ぐせが増えて、既存 skill を更新したくなった？

`transform.skill` は update-first です。
- 主ルート：既存 skill を新規コーパスで継続更新
- 任意ルート：ゼロからコールドスタート蒸留

## インストール
```bash
git clone https://github.com/Xuan-0929/transform.skill.git
cd transform.skill
```

任意（複数ディレクトリで使う場合）：
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform.skill
```

## クイックスタート（Nuwa / colleague.skill 風）
### 1) コーパスフォルダを準備
```bash
mkdir -p corpus/bootstrap corpus/incoming
```

推奨配置：
- `corpus/bootstrap/`：初回蒸留
- `corpus/incoming/`：増分更新

### 2) Claude ランタイムにログイン（初回のみ）
```bash
claude auth login
```

### 3) Claude Code にそのまま指示（推奨）
```text
distill-from-corpus-path を使って ./corpus/incoming/week2.json で persona=laojin を更新、new-corpus-weight=0.2
```

任意（コールドスタート）：
```text
distill-from-corpus-path を使って ./corpus/bootstrap/day0.json から persona=laojin を初回蒸留
```

### 4) 直接コマンド実行（任意）
```bash
DISTILL_NEW_CORPUS_WEIGHT=0.2 \
./skills/distill-from-corpus-path/scripts/run_distill_from_path.sh \
./corpus/incoming/week2.json \
laojin
```

## 出力先
- バージョン skill：`.distill/personas/<persona>/versions/<version>/skill/`
- Agent Skills export：`.distill/personas/<persona>/exports/<version>/agentskills/`
- Codex export：`.distill/personas/<persona>/exports/<version>/codex/`

## 重みの目安
- `0.1-0.3`：保守的（旧人格を強く保持）
- `0.4-0.6`：バランス型
- `0.7-1.0`：新特性を積極反映

## よくあるエラー
- `Claude CLI not found`：Claude Code CLI を先に導入
- `Claude CLI is not logged in`：`claude auth login`
- `Error: claude native binary not installed`：CLI を再インストール、または native installer を実行
```bash
npm install -g @anthropic-ai/claude-code
node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"
```
- `Cannot locate persona-distill project root`：リポジトリルートで実行、または以下設定
```bash
export DISTILL_PROJECT_ROOT=/absolute/path/to/transform.skill
```
