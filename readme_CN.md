<div align="center">

# transform-skill（中文说明）

[中文版入口 README](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

这里是中文辅助页。最新产品说明、快速启动和场景示例请以 [README.md](./README.md) 为准。

## 快速提醒

- 主入口：`/transform-skill`
- 默认路径：更新已有 skill（update-first）
- 冷启动：可选能力
- 多人语料：务必指定 `target_speaker`
- 兼容入口：`distill-from-corpus-path`（保留）

## 一句启动示例

```text
请使用 transform-skill 更新 friend_id=<friend_id>：
语料=./corpus/incoming/<new_corpus>.json，
target_speaker=<target_speaker>，new-corpus-weight=0.2。
```

安装与运维细节见 [INSTALL.md](./INSTALL.md)。
