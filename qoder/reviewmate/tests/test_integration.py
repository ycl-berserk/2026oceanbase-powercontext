from __future__ import annotations

import os
from pathlib import Path

import pytest

from reviewmate.chunking import parse_document
from reviewmate.embeddings import Embedder
from reviewmate.store import SeekDBStore

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("REVIEWMATE_RUN_INTEGRATION") != "1",
    reason="设置 REVIEWMATE_RUN_INTEGRATION=1 后运行 seekdb 集成测试",
)
def test_ingest_and_hybrid_search(tmp_path: Path) -> None:
    embedder = Embedder("BAAI/bge-small-zh-v1.5", dim=512)
    store = SeekDBStore(tmp_path / "db", embed_dim=512)
    try:
        path = tmp_path / "vm.md"
        path.write_text(
            "---\ncourse: 操作系统\ntitle: 虚拟内存\n---\n\n"
            "## 页面置换\n\nFIFO 按进入顺序淘汰，可能出现 Belady 异常。"
            "LRU 按最近使用时间淘汰，通常更接近 OPT。\n",
            encoding="utf-8",
        )
        document = parse_document(path)
        vectors = embedder.embed_documents([chunk.embed_text for chunk in document.chunks])
        store.upsert_document(document, vectors)
        store._warm_vector_index()

        result = store.search(
            "FIFO 的 Belady 异常",
            embedder.embed_query("FIFO 的 Belady 异常"),
            limit=3,
        )
        assert result.evidence
        assert result.evidence[0].doc_id == "vm"
        assert result.trace["channels"]["fulltext"] >= 1
        assert result.trace["channels"]["vector"] >= 1
    finally:
        store.close()
