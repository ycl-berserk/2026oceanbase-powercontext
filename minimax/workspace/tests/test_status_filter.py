from __future__ import annotations

from ticket_service.service import list_tickets


def test_filters_open_tickets(tickets):
    result = list_tickets(tickets, status="open")
    assert {ticket.ticket_id for ticket in result} == {"T1", "T2", "T4"}


def test_unknown_status_returns_empty(tickets):
    assert list_tickets(tickets, status="archived") == []


def test_does_not_mutate_input(tickets):
    snapshot = list(tickets)
    list_tickets(tickets, status="open", limit=2)
    assert tickets == snapshot
