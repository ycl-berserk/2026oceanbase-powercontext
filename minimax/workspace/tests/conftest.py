from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticket_service.models import Ticket  # noqa: E402


@pytest.fixture
def tickets() -> list[Ticket]:
    return [
        Ticket("T1", "登录失败", "open", "P1", "2026-10-01T09:00:00"),
        Ticket("T2", "支付超时", "open", "P0", "2026-10-02T09:00:00"),
        Ticket("T3", "导出报错", "closed", "P2", "2026-10-03T09:00:00"),
        Ticket("T4", "权限申请", "open", "P0", "2026-10-04T09:00:00"),
        Ticket("T5", "页面卡顿", "closed", "P1", "2026-10-05T09:00:00"),
    ]
