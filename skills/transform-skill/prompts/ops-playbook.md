# Maintenance Playbook

## Supported maintenance actions

- list
- history
- rollback
- export
- correct
- doctor

## Execution Templates

```bash
./tools/run_transform.sh list
./tools/run_transform.sh history --friend-id <friend_id>
./tools/run_transform.sh rollback --friend-id <friend_id> --to-version <version>
./tools/run_transform.sh export --friend-id <friend_id> --target both
./tools/run_transform.sh correct --friend-id <friend_id> --correction-text "<instruction>"
./tools/run_transform.sh doctor
```

## Response style

- Show exact action executed
- Show key result fields
- For rollback/export, always return target version and output paths
