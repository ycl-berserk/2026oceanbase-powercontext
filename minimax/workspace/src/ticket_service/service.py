"""工单查询服务。"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Ticket


def list_tickets(
    tickets: Sequence[Ticket],
    status: str | None = None,
    priority: str | None = None,
    limit: int = 10,
) -> list[Ticket]:
    """按状态过滤工单并截断到 limit。

    R4（优先级过滤）、R5（参数校验）与 R6（稳定排序）尚未实现。
    """
    items = [ticket for ticket in tickets if status is None or ticket.status == status]
    return items[:limit]
