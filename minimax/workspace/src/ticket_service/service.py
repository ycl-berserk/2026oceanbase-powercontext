"""工单查询服务。"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import InvalidFilter
from .models import PRIORITY_ORDER, Ticket


def list_tickets(
    tickets: Sequence[Ticket],
    status: str | None = None,
    priority: str | None = None,
    limit: int = 10,
) -> list[Ticket]:
    """过滤、排序工单并截断到 limit。"""
    if priority is not None and priority not in PRIORITY_ORDER:
        raise InvalidFilter(f"无效的优先级：{priority}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise InvalidFilter(f"无效的 limit：{limit}")

    items = [
        ticket
        for ticket in tickets
        if (status is None or ticket.status == status)
        and (priority is None or ticket.priority == priority)
    ]
    items.sort(key=lambda ticket: (PRIORITY_ORDER[ticket.priority], ticket.created_at), reverse=True)
    items.sort(key=lambda ticket: PRIORITY_ORDER[ticket.priority])
    return items[:limit]
