"""查询参数错误。"""

from __future__ import annotations


class InvalidFilter(ValueError):
    """查询参数不符合规格（R5）。"""
