# 验证样例：补全 list_tickets 的 R4–R6

## 任务

为 `workspace/src/ticket_service/service.py` 的 `list_tickets` 实现规格 R4、R5、R6：

- R4：支持 `priority` 过滤（`P0` / `P1` / `P2`，`None` 表示不过滤）；
- R5：非法 `priority`、越界或非整数的 `limit` 抛出 `InvalidFilter`；
- R6：结果按优先级升序、同优先级按 `created_at` 倒序，稳定排序。

## 必须命中的来源

| 类型 | 必须出现在上下文中的来源 |
| --- | --- |
| 规格 | `specs/tickets.md#R4`、`#R5`、`#R6` |
| 代码 | `src/ticket_service/service.py` 的 `list_tickets`；`src/ticket_service/errors.py` 的 `InvalidFilter` |
| 测试 | `tests/test_priority_filter.py` 的 `test_filters_by_priority`、`test_rejects_unknown_priority`、`test_rejects_limit_out_of_range`、`test_orders_by_priority_then_recency`、`test_combines_status_and_priority` |

## 预期输出

`python -m sdd_context plan --task "<任务>" --task-id sdd-r4-r6 --json` 的 JSON 中：

- `specs` 覆盖 R4、R5、R6 三个条目，且每个 `source` 指向真实存在的行号；
- `code` 包含 `list_tickets`，行号范围覆盖函数体；
- `tests` 包含上表的目标测试；
- `status` 来自 PowerContext，`todo` / `done` / `verified` 与任务记录一致。

## 执行步骤

```bash
python -m sdd_context ingest --project workspace
python -m sdd_context plan --task "为 list_tickets 增加 priority 过滤，非法 priority 与越界 limit 抛出 InvalidFilter，结果按优先级和创建时间稳定排序" \
  --task-id sdd-r4-r6 --json
PYTHONPATH=workspace/src python -m pytest -q workspace/tests
```

## 重置

```bash
rm -rf data/seekdb data/powercontext
python -m sdd_context ingest --project workspace
```

目标测试在实现前应当失败（见 `docs/evidence/before-target.log`），实现后应全部通过。
