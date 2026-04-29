# /transform-skill Entry Intake

## Goal

Classify the request into one of:
- `update` (default)
- `create`
- `maintenance`

## Intake Script (short, customer-facing)

When the user invokes `/transform-skill`, confirm only what is needed:

1. `你这次是更新已有 skill 还是从 0 冷启动？（默认更新）`
2. `语料路径是哪个？`
3. `目标对象在语料中的说话人是谁？（多人语料必填）`
4. `如果是更新，新语料权重想保守(0.2)、平衡(0.5)还是激进(0.8)？`

## Classification Rules

- If user says update/迭代/补充语料/保持原风格 -> `update`
- If user says 新建/从0/第一次蒸馏 -> `create`
- If user says 列表/历史/回滚/导出/纠偏/诊断 -> `maintenance`

Default to `update` when ambiguous.
