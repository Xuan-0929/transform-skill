<div align="center">

# transform-skill

[中文版](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

このページは日本語サポート版です。プロダクト紹介・導入フロー・利用例の最新版は [README.md](./README.md) を参照してください。

## クイックメモ

- メイン入口：`/transform-skill`
- 既定ルート：既存 skill の update-first 更新
- コールドスタート：任意
- 複数話者コーパス：`target_speaker` を必ず指定
- 互換入口：`distill-from-corpus-path` も継続提供

## 一行例

```text
transform-skill で friend_id=<friend_id> を更新してください。
input=./corpus/incoming/<new_corpus>.json,
target_speaker=<target_speaker>, new-corpus-weight=0.2。
```

導入・運用の詳細は [INSTALL.md](./INSTALL.md) を参照してください。
