# Cold-Start Playbook (Optional Path)

## When to use

Only use cold-start when persona does not exist yet or user explicitly asks for new persona creation.

## Required inputs

- `input` corpus path
- `friend_id`
- `target_speaker` (for multi-speaker corpus)

## Execution Template

```bash
./tools/run_transform.sh create \
  --input <seed_corpus_path> \
  --friend-id <friend_id> \
  --target-speaker <target_speaker> \
  --target both
```

## Guardrails

- If persona already exists, suggest update path first.
- Do not overwrite existing persona silently.
