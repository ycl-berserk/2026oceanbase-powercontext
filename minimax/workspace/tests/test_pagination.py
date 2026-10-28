from __future__ import annotations

from ticket_service.models import Ticket
from ticket_service.service import list_tickets


def test_limit_caps_result(tickets):
    assert len(list_tickets(tickets, limit=2)) == 2


def test_default_limit_is_ten():
    many = [
        Ticket(f"T{index}", "示例", "open", "P1", f"2026-10-{index:02d}T00:00:00")
        for index in range(1, 13)
    ]
    assert len(list_tickets(many)) == 10
