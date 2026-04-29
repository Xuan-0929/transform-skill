<div align="center">

# transform-skill

[中文版](./README.md) · [English](./readme_EN.md) · [日本語](./readme_JP.md)

</div>

This is the English helper page. For the full product narrative, onboarding flow, and examples, use [README.md](./README.md).

## Quick Notes

- Primary entry: `/transform-skill`
- Default path: update-first evolution of an existing skill
- Cold-start: optional path
- Multi-speaker corpus: always set `target_speaker`
- Legacy compatibility: `distill-from-corpus-path` is still available

## One-line Example

```text
Use transform-skill to update friend_id=<friend_id> with
input=./corpus/incoming/<new_corpus>.json,
target_speaker=<target_speaker>, new-corpus-weight=0.2.
```

See [INSTALL.md](./INSTALL.md) for installation and ops details.
