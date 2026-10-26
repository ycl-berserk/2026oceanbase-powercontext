from __future__ import annotations

from pathlib import Path

import pytest

from reviewmate.chunking import parse_document, split_frontmatter

SAMPLE = """---
course: 操作系统
title: 虚拟内存
source: 自编
license: CC BY 4.0
tags: 页表, LRU
---

# 虚拟内存

<!-- page: 1 -->
## 页表

虚拟地址通过页表映射到物理页框。TLB 是页表项的硬件缓存。

<!-- page: 2 -->
## 页面置换

FIFO 按进入顺序淘汰。LRU 按最近使用时间淘汰，通常更接近 OPT。
"""


def test_split_frontmatter() -> None:
    meta, body = split_frontmatter(SAMPLE)
    assert meta["course"] == "操作系统"
    assert meta["tags"] == "页表, LRU"
    assert body.startswith("# 虚拟内存")


def test_parse_document_tracks_heading_and_page(tmp_path: Path) -> None:
    path = tmp_path / "os-vm.md"
    path.write_text(SAMPLE, encoding="utf-8")
    document = parse_document(path)

    assert document.doc_id == "os-vm"
    assert document.course == "操作系统"
    assert document.title == "虚拟内存"
    assert document.tags == ("页表", "LRU")
    assert [chunk.heading for chunk in document.chunks] == ["页表", "页面置换"]
    assert [chunk.page_no for chunk in document.chunks] == [1, 2]
    assert document.chunks[0].chunk_id == "os-vm#000"
    assert "课程：操作系统" in document.chunks[0].embed_text
    assert all(chunk.char_len <= 420 for chunk in document.chunks)


def test_long_section_is_split_without_losing_text(tmp_path: Path) -> None:
    paragraph = "这是一个用于测试切分的长句子，包含足够多的字符。" * 30
    path = tmp_path / "long.md"
    path.write_text(f"## 长章节\n\n{paragraph}\n", encoding="utf-8")
    document = parse_document(path)
    assert len(document.chunks) > 1
    assert all(chunk.char_len <= 420 for chunk in document.chunks)
    assert "长章节" == document.chunks[0].heading


def test_rejects_unsupported_suffix(tmp_path: Path) -> None:
    path = tmp_path / "data.pdf"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_document(path)
