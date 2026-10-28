# MiniMax 开发记录

本记录对应一次真实的代码修改：`workspace/src/ticket_service/service.py` 的 `list_tickets` 从"只支持状态过滤"改为满足规格 R4–R6。记录中的上下文、模型输出与最终提交的 diff 一一对应。

## 1. 任务与调用渠道

| 项 | 值 |
| --- | --- |
| 任务 ID | `sdd-r4-r6` |
| 任务 | 为 `list_tickets` 增加 priority 过滤，非法 priority 与越界 limit 抛出 `InvalidFilter`，结果按优先级和创建时间稳定排序 |
| 模型 | **MiniMax M3**（`opencode-go/minimax-m3`） |
| 访问渠道 | OpenCode Go 订阅（`https://opencode.ai/zen/go`，Anthropic 兼容的 `/v1/messages`） |
| 会话 | `ses_e7dc51992ffeNO5JbOH1ekSSNF` |
| 时间 | 2026-10-28 |
| 最终提交 | `d32308e0`（`fix(minimax): implement priority filter, validation and stable ordering`） |

## 2. 提供给模型的上下文

上下文由本项目 `sddctx plan` 生成（seekdb 召回），原样交给模型：

```bash
python -m sdd_context plan \
  --task "为 list_tickets 增加 priority 过滤，非法 priority 与越界 limit 抛出 InvalidFilter，结果按优先级和创建时间稳定排序" \
  --task-id sdd-r4-r6 --no-state
```

```text
# 任务：为 list_tickets 增加 priority 过滤，非法 priority 与越界 limit 抛出 InvalidFilter，结果按优先级和创建时间稳定排序

## 适用规格
- R6 结果排序：按 P0 < P1 < P2 升序；同优先级按 created_at 倒序；created_at 相同保持输入顺序（稳定排序）。
- R5 参数校验：priority 不在 P0/P1/P2 中抛 InvalidFilter；limit 必须是 1..100 的整数，越界或非整数抛 InvalidFilter。
- R4 优先级过滤：priority 取值为 P0/P1/P2；None 时不过滤。
- R1 列表查询：不得修改传入的列表或工单对象；不得依赖调用方预先排序。
- R2 状态过滤：status 为 None 时不过滤；未知状态返回空列表。

## 相关代码
- InvalidFilter（src/ticket_service/errors.py）
- list_tickets（src/ticket_service/service.py，当前只实现状态过滤与 limit 截断）
- Ticket（src/ticket_service/models.py，含 PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}）

## 验证测试
- tests/test_priority_filter.py 的 5 个用例
```

同时要求：只改 `service.py`；不改测试；保持 R1–R3 行为；运行 `pytest workspace/tests`。

## 3. 模型输出（摘要与 diff）

模型只修改了 `workspace/src/ticket_service/service.py`：

- 引入 `InvalidFilter` 与 `PRIORITY_ORDER`；
- `priority` 非 `None` 且不在 `P0/P1/P2` 时抛 `InvalidFilter`；
- `limit` 不是 1..100 的整数（含 `bool`）时抛 `InvalidFilter`；
- 先按 `(priority, created_at)` 倒序排列，再按 priority 稳定排序，得到"优先级升序 + 同优先级时间倒序"；
- 过滤和排序都基于新列表，不修改入参。

```diff
diff --git a/minimax/workspace/src/ticket_service/service.py b/minimax/workspace/src/ticket_service/service.py
index f93fe628..cb9463a3 100644
--- a/minimax/workspace/src/ticket_service/service.py
+++ b/minimax/workspace/src/ticket_service/service.py
@@ -4,7 +4,8 @@ from __future__ import annotations
 
 from collections.abc import Sequence
 
-from .models import Ticket
+from .errors import InvalidFilter
+from .models import PRIORITY_ORDER, Ticket
 
 
 def list_tickets(
@@ -13,9 +14,18 @@ def list_tickets(
     priority: str | None = None,
     limit: int = 10,
 ) -> list[Ticket]:
-    """按状态过滤工单并截断到 limit。
+    """过滤、排序工单并截断到 limit。"""
+    if priority is not None and priority not in PRIORITY_ORDER:
+        raise InvalidFilter(f"无效的优先级：{priority}")
+    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
+        raise InvalidFilter(f"无效的 limit：{limit}")
 
-    R4（优先级过滤）、R5（参数校验）与 R6（稳定排序）尚未实现。
-    """
-    items = [ticket for ticket in tickets if status is None or ticket.status == status]
+    items = [
+        ticket
+        for ticket in tickets
+        if (status is None or ticket.status == status)
+        and (priority is None or ticket.priority == priority)
+    ]
+    items.sort(key=lambda ticket: (PRIORITY_ORDER[ticket.priority], ticket.created_at), reverse=True)
+    items.sort(key=lambda ticket: PRIORITY_ORDER[ticket.priority])
     return items[:limit]
```

## 4. 落地与验证

| 阶段 | 命令 | 结果 |
| --- | --- | --- |
| 改前（提交 `6da7b4a3`） | `pytest workspace/tests` | 5 passed, **7 failed**（目标测试因 R4–R6 未实现而失败），见 `docs/evidence/before-target.log` |
| 改后（提交 `d32308e0`） | `pytest workspace/tests` | **12 passed**，见 `docs/evidence/after-target.log` |
| 端到端 | `python scripts/verify.py` | 12/12，见 `docs/verification/report.json` |

红态可现场复现：`make red-green`（临时 worktree 检出 `6da7b4a3` 跑目标测试，再跑当前版本）。

## 5. 规格 → 代码 → 测试对应

| 规格 | 代码实现 | 对应测试 |
| --- | --- | --- |
| R4 优先级过滤 | `items` 推导式中 `priority is None or ticket.priority == priority` | `test_filters_by_priority`、`test_combines_status_and_priority` |
| R5 参数校验 | 函数入口两处 `raise InvalidFilter` | `test_rejects_unknown_priority`、`test_rejects_limit_out_of_range`（-1/0/101） |
| R6 稳定排序 | 两次稳定排序（先时间倒序，再优先级升序） | `test_orders_by_priority_then_recency` |

## 6. 人工干预说明

- 本次 `service.py` 的修改由模型一次产出，**未做人工改码**；提交 `d32308e0` 的 diff 与上方完全一致。
- 同一提交期内还修了上下文模块自身的两个缺陷（检索结果缺 `text`、重复 `start` 产生重复待办），属于模块修复，见提交 `43678c4a`，不属于本次模型改码。
