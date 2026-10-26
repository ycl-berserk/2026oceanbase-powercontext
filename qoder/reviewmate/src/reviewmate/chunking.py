from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
PAGE_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff-]+", re.UNICODE)

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    ordinal: int
    heading: str
    page_no: int | None
    content: str
    embed_text: str
    char_len: int


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    course: str
    title: str
    source: str
    license: str
    tags: tuple[str, ...]
    path: str
    sha256: str
    chunks: tuple[Chunk, ...]


def split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw
    block = raw[3:end].strip("\n")
    body = raw[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, body


def _slug(text: str, fallback: str = "doc") -> str:
    slug = SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or fallback


def _tail(text: str, limit: int) -> str:
    if limit <= 0 or not text:
        return ""
    tail = text[-limit:]
    boundary = re.search(r"[。！？!?；;\n]", tail)
    if boundary and boundary.end() < len(tail) - 8:
        return tail[boundary.end() :].strip()
    return tail.strip()


def _pack(text: str, max_chars: int, overlap: int) -> list[str]:
    overlap = min(max(0, overlap), max_chars // 3)
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            units.append(paragraph)
        else:
            units.extend(s.strip() for s in SENTENCE_RE.findall(paragraph) if s.strip())

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n{unit}" if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = _tail(current, overlap)
            current = f"{tail}\n{unit}" if tail else unit
        else:
            current = unit
        while len(current) > max_chars:
            chunks.append(current[:max_chars].strip())
            current = current[max_chars - overlap :].strip()
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def _sections(body: str, default_heading: str = "正文") -> tuple[str | None, list[tuple[str, int | None, str]]]:
    title: str | None = None
    heading = default_heading
    page: int | None = None
    buffer: list[str] = []
    sections: list[tuple[str, int | None, str]] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if text:
            sections.append((heading, page, text))
        buffer = []

    for line in body.splitlines():
        page_match = PAGE_RE.search(line)
        if page_match and not line.replace(page_match.group(0), "").strip():
            flush()
            page = int(page_match.group(1))
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            if level == 1 and title is None:
                title = text
            else:
                heading = text
            continue
        buffer.append(line)
    flush()
    return title, sections


def _embed_text(course: str, title: str, heading: str, content: str) -> str:
    return f"课程：{course}；文档：{title}；章节：{heading}。\n{content}"


def parse_document(
    path: Path,
    *,
    max_chars: int = 420,
    overlap: int = 80,
    course_override: str | None = None,
) -> ParsedDocument:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的资料格式：{path.suffix}（支持 .md / .markdown / .txt）")

    raw = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(raw)
    doc_title, sections = _sections(body)
    title = meta.get("title") or doc_title or path.stem
    course = course_override or meta.get("course") or "未分类"
    source = meta.get("source") or "本地课程笔记"
    license_name = meta.get("license") or "未声明"
    tags = tuple(t.strip() for t in re.split(r"[,，、]", meta.get("tags", "")) if t.strip())
    doc_id = _slug(meta.get("doc_id") or path.stem)

    chunks: list[Chunk] = []
    ordinal = 0
    for heading, page, text in sections:
        for piece in _pack(text, max_chars=max_chars, overlap=overlap):
            chunk_id = f"{doc_id}#{ordinal:03d}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    ordinal=ordinal,
                    heading=heading,
                    page_no=page,
                    content=piece,
                    embed_text=_embed_text(course, title, heading, piece),
                    char_len=len(piece),
                )
            )
            ordinal += 1

    if not chunks:
        raise ValueError(f"{path} 中没有可索引的正文内容")

    return ParsedDocument(
        doc_id=doc_id,
        course=course,
        title=title,
        source=source,
        license=license_name,
        tags=tags,
        path=str(path),
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        chunks=tuple(chunks),
    )
