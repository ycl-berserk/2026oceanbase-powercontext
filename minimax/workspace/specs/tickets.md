# 工单查询规格

`ticket_service` 为内部工单面板提供查询能力。本文件是 `list_tickets` 的对外行为规格，评审与测试均以此为准。

### R1 列表查询

`list_tickets(tickets, status=None, priority=None, limit=10)` 返回工单列表。

- 不得修改传入的列表或其中的工单对象；
- 不得依赖调用方预先排序。

### R2 状态过滤

`status` 为 `None` 时不做状态过滤；否则只返回 `status` 相同的工单。

未知状态返回空列表，不抛异常。

### R3 返回数量

默认最多返回 10 条；`limit` 用于限制返回条数。

### R4 优先级过滤

`priority` 取值为 `P0`、`P1`、`P2`。为 `None` 时不做优先级过滤；否则只返回优先级相同的工单。

### R5 参数校验

- `priority` 不在 `P0`、`P1`、`P2` 中时抛出 `InvalidFilter`；
- `limit` 必须是 1 到 100 之间的整数，越界或非整数时抛出 `InvalidFilter`。

### R6 结果排序

过滤后的结果按优先级 `P0` < `P1` < `P2` 升序排列；同一优先级按 `created_at` 倒序排列；`created_at` 相同时保持输入顺序（稳定排序）。
