from __future__ import annotations

from reviewmate.store import fuse_rankings


def row(chunk_id: str, *, score: float | None = None, distance: float | None = None) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": "os-vm",
        "course": "操作系统",
        "heading": "页面置换",
        "page_no": 4,
        "content": "内容",
        "fts_score": score,
        "distance": distance,
    }


def test_chunk_hit_by_both_channels_wins() -> None:
    fused = fuse_rankings(
        [row("a", score=9.0), row("b", score=3.0)],
        [row("b", distance=0.8), row("c", distance=0.9)],
        limit=3,
    )
    assert [item["chunk_id"] for item in fused] == ["b", "a", "c"]
    assert fused[0]["fts_rank"] == 2
    assert fused[0]["vector_rank"] == 1
    assert fused[0]["score"] == 1.0


def test_single_channel_still_works() -> None:
    fused = fuse_rankings([], [row("a", distance=0.7), row("b", distance=0.8)], limit=2)
    assert [item["chunk_id"] for item in fused] == ["a", "b"]
    assert fused[0]["score"] == 1.0
    assert fused[0]["fts_rank"] is None


def test_limit_is_applied() -> None:
    fused = fuse_rankings([row("a", score=1.0), row("b", score=0.8)], [], limit=1)
    assert len(fused) == 1
    assert fused[0]["chunk_id"] == "a"
