# Update-First Playbook

## Why update-first

Use update-first to preserve stable personality anchors while absorbing new corpus.

## Parameters

- `friend_id`: stable identifier of existing persona
- `input`: new corpus path
- `target_speaker`: required for multi-speaker corpus
- `new_corpus_weight`: update intensity

## Weight Recommendations

- `0.10-0.30`: conservative, strong old-style retention
- `0.40-0.60`: balanced blend
- `0.70-1.00`: aggressive adaptation

## Execution Template

```bash
./tools/run_transform.sh update \
  --input <new_corpus_path> \
  --friend-id <friend_id> \
  --target-speaker <target_speaker> \
  --new-corpus-weight <weight> \
  --target both
```

## Summary Template

- 更新对象：`<friend_id>`
- 目标说话人：`<target_speaker>`
- 新语料权重：`<weight>`
- 版本结果：`<version>` (`<status>`)
