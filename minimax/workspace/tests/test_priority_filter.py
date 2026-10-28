"""R4 / R5 / R6 的目标测试：修改前应当失败。"""

from __future__ import annotations

import pytest

from ticket_service.errors import InvalidFilter
from ticket_service.service import list_tickets


def test_filters_by_priority(tickets):
    result = list_tickets(tickets, priority="P1")
    assert {ticket.ticket_id for ticket in result} == {"T1", "T5"}


def test_rejects_unknown_priority(tickets):
    with pytest.raises(InvalidFilter):
        list_tickets(tickets, priority="P9")


@pytest.mark.parametrize("limit", [-1, 0, 101])
def test_rejects_limit_out_of_range(tickets, limit):
    with pytest.raises(InvalidFilter):
        list_tickets(tickets, limit=limit)


def test_orders_by_priority_then_recency(tickets):
    assert [ticket.ticket_id for ticket in list_tickets(tickets)] == [
        "T4",
        "T2",
        "T5",
        "T1",
        "T3",
    ]


def test_combines_status_and_priority(tickets):
    result = list_tickets(tickets, status="open", priority="P0")
    assert [ticket.ticket_id for ticket in result] == ["T4", "T2"]
