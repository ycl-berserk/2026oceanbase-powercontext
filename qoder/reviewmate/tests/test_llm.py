from __future__ import annotations

from pathlib import Path

from reviewmate.config import Settings
from reviewmate.llm import AnswerWriter, select_answer_evidence
from reviewmate.store import Evidence


def settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        db_path=tmp_path / "seekdb",
        embed_model="BAAI/bge-small-zh-v1.5",
        embed_dim=512,
        embed_cache=None,
        top_k=6,
        powercontext_url="http://127.0.0.1:8100",
        powercontext_timeout=5,
        llm_provider="auto",
        deepseek_api_key="",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat",
    )


def evidence(chunk_id: str, score: float, *, fts_rank: int | None = None) -> Evidence:
    return Evidence(
        chunk_id=chunk_id,
        doc_id="os-vm",
        course="操作系统",
        heading="LRU 与 FIFO 的对比",
        page_no=4,
        content="FIFO 可能产生 Belady 异常。LRU 通常更接近 OPT。",
        title="虚拟内存与页面置换",
        source="自编课程笔记",
        fts_rank=fts_rank,
        vector_rank=1,
        score=score,
    )


def test_select_evidence_stops_at_low_relevance() -> None:
    selected = select_answer_evidence(
        [evidence("a", 1.0, fts_rank=1), evidence("noise", 0.49), evidence("b", 0.48)]
    )
    assert [item.chunk_id for item in selected] == ["a"]


def test_extractive_answer_cites_only_used_chunks(tmp_path: Path) -> None:
    writer = AnswerWriter(settings(tmp_path))
    generated = writer.answer(
        "LRU 和 FIFO 有什么区别？",
        [evidence("a", 1.0, fts_rank=1), evidence("noise", 0.49)],
        [],
        None,
    )
    assert generated.mode == "extractive"
    assert "[1]" in generated.text
    assert generated.used_chunk_ids == ["a"]
    assert "本地摘录模式" in generated.text


def test_template_plan_mentions_weak_point(tmp_path: Path) -> None:
    from reviewmate.memory import MemoryHit

    writer = AnswerWriter(settings(tmp_path))
    point = MemoryHit(
        entry_id="m1",
        text="薄弱点：FIFO 的 Belady 异常",
        kind="weak-point",
        score=1.0,
        matched_by=["list"],
        citation={},
    )
    generated = writer.plan(
        course="操作系统",
        weak_points=[point],
        documents=[
            {
                "doc_id": "os-vm",
                "title": "虚拟内存与页面置换",
                "course": "操作系统",
                "chunk_count": 5,
            }
        ],
    )
    assert generated.mode == "template"
    assert "Belady" in generated.text
    assert "虚拟内存与页面置换" in generated.text
