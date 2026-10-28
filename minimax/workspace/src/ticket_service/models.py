"""工单查询领域模型。"""

from __future__ import annotations

from dataclasses import dataclass

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    title: str
    status: str
    priority: str
    created_at: str
