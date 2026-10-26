from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pylibseekdb as seekdb
import pymysql

from .chunking import ParsedDocument
from .embeddings import vector_literal


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Evidence:
    chunk_id: str
    doc_id: str
    course: str
    heading: str
    page_no: int | None
    content: str
    title: str = ""
    source: str = ""
    fts_rank: int | None = None
    vector_rank: int | None = None
    fts_score: float | None = None
    distance: float | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    evidence: list[Evidence] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


def fuse_rankings(
    fts_rows: list[dict[str, Any]],
    vector_rows: list[dict[str, Any]],
    *,
    limit: int = 6,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """用 Reciprocal Rank Fusion 融合全文与向量两路候选。"""
    merged: dict[str, dict[str, Any]] = {}
    for channel, rows in (("fts", fts_rows), ("vector", vector_rows)):
        for rank, row in enumerate(rows, start=1):
            chunk_id = row["chunk_id"]
            item = merged.get(chunk_id)
            if item is None:
                item = dict(row)
                item["fts_rank"] = None
                item["vector_rank"] = None
                item["score"] = 0.0
                merged[chunk_id] = item
            item[f"{channel}_rank"] = rank
            item["score"] += 1.0 / (rrf_k + rank)
            if channel == "vector":
                item["distance"] = row.get("distance")
            else:
                item["fts_score"] = row.get("fts_score")

    ranked = sorted(
        merged.values(),
        key=lambda item: (-item["score"], item.get("distance") or 0.0, item["chunk_id"]),
    )[:limit]
    if ranked:
        best = ranked[0]["score"]
        for item in ranked:
            item["score"] = round(item["score"] / best, 4) if best else 0.0
    return ranked


class SeekDBStore:
    """seekdb 嵌入式存储：文档、切块、向量与检索日志。"""

    def __init__(
        self,
        db_path: Path,
        *,
        embed_dim: int = 512,
        embed_model: str = "BAAI/bge-small-zh-v1.5",
        warmup: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.embed_dim = embed_dim
        self.embed_model = embed_model
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._instance = seekdb.open(str(self.db_path))
        options = dict(self._instance.connection_options())
        options.setdefault("database", "test")
        options["cursorclass"] = pymysql.cursors.DictCursor
        options["autocommit"] = False
        self._conn = pymysql.connect(**options)
        self._ensure_schema()
        if warmup:
            self._warm_vector_index()

    # ---------- schema ----------

    def _ensure_schema(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS meta (
              meta_key VARCHAR(64) PRIMARY KEY,
              meta_value VARCHAR(255) NOT NULL
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS documents (
              doc_id VARCHAR(128) PRIMARY KEY,
              course VARCHAR(128) NOT NULL,
              title VARCHAR(255) NOT NULL,
              source VARCHAR(512) NOT NULL,
              license VARCHAR(128) NOT NULL,
              tags VARCHAR(512) NOT NULL,
              path VARCHAR(512) NOT NULL,
              sha256 CHAR(64) NOT NULL,
              chunk_count INT NOT NULL,
              ingested_at VARCHAR(32) NOT NULL
            ) ORGANIZATION = HEAP
            """,
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
              chunk_id VARCHAR(64) PRIMARY KEY,
              doc_id VARCHAR(128) NOT NULL,
              course VARCHAR(128) NOT NULL,
              heading VARCHAR(255) NOT NULL,
              page_no INT NULL,
              ordinal INT NOT NULL,
              content TEXT NOT NULL,
              embed_text TEXT NOT NULL,
              char_len INT NOT NULL,
              embedding VECTOR({self.embed_dim}) NOT NULL,
              FULLTEXT INDEX ft_chunks_content (content) WITH PARSER NGRAM,
              VECTOR INDEX vidx_chunks_embedding (embedding)
                WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag)
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS qa_log (
              qa_id VARCHAR(64) PRIMARY KEY,
              session_id VARCHAR(128) NOT NULL,
              question TEXT NOT NULL,
              course VARCHAR(128) NULL,
              top_k INT NOT NULL,
              chunk_ids TEXT NOT NULL,
              answer_mode VARCHAR(32) NOT NULL,
              latency_ms INT NOT NULL,
              created_at VARCHAR(32) NOT NULL
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id VARCHAR(128) PRIMARY KEY,
              scope_id VARCHAR(128) NOT NULL,
              title VARCHAR(255) NOT NULL,
              created_at VARCHAR(32) NOT NULL,
              updated_at VARCHAR(32) NOT NULL
            ) ORGANIZATION = HEAP
            """,
        ]
        with self._lock:
            with self._conn.cursor() as cursor:
                for statement in ddl:
                    cursor.execute(statement)
            self._conn.commit()
            self._check_embedding_identity()

    def _check_embedding_identity(self) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT meta_key, meta_value FROM meta")
            values = {row["meta_key"]: row["meta_value"] for row in cursor.fetchall()}
            expected = {"embedding_dim": str(self.embed_dim), "embedding_model": self.embed_model}
            for key, value in expected.items():
                current = values.get(key)
                if current is None:
                    cursor.execute(
                        "INSERT INTO meta (meta_key, meta_value) VALUES (%s, %s)", (key, value)
                    )
                elif current != value:
                    raise RuntimeError(
                        f"数据库的 {key}={current} 与当前配置 {value} 不一致。"
                        "请恢复原配置，或删除 data/seekdb 后重新导入资料。"
                    )
            self._conn.commit()

    def _warm_vector_index(self, attempts: int = 20) -> None:
        if self.chunk_count() == 0:
            return
        probe = vector_literal([0.0] * self.embed_dim)
        for _ in range(attempts):
            with self._lock:
                with self._conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT chunk_id FROM chunks "
                        "ORDER BY l2_distance(embedding, %s) APPROXIMATE LIMIT 1",
                        (probe,),
                    )
                    if cursor.fetchall():
                        return
            time.sleep(0.25)

    # ---------- ingest ----------

    def upsert_document(self, document: ParsedDocument, vectors: list[list[float]]) -> dict[str, Any]:
        if len(document.chunks) != len(vectors):
            raise ValueError("切块数量与向量数量不一致")
        now = utc_now()
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute("DELETE FROM chunks WHERE doc_id=%s", (document.doc_id,))
                cursor.execute("DELETE FROM documents WHERE doc_id=%s", (document.doc_id,))
                for chunk, vector in zip(document.chunks, vectors, strict=True):
                    cursor.execute(
                        """
                        INSERT INTO chunks
                          (chunk_id, doc_id, course, heading, page_no, ordinal,
                           content, embed_text, char_len, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            chunk.chunk_id,
                            chunk.doc_id,
                            document.course,
                            chunk.heading,
                            chunk.page_no,
                            chunk.ordinal,
                            chunk.content,
                            chunk.embed_text,
                            chunk.char_len,
                            vector_literal(vector),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO documents
                      (doc_id, course, title, source, license, tags, path,
                       sha256, chunk_count, ingested_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document.doc_id,
                        document.course,
                        document.title,
                        document.source,
                        document.license,
                        ", ".join(document.tags),
                        document.path,
                        document.sha256,
                        len(document.chunks),
                        now,
                    ),
                )
            self._conn.commit()
        return {
            "doc_id": document.doc_id,
            "title": document.title,
            "course": document.course,
            "chunks": len(document.chunks),
        }

    def delete_document(self, doc_id: str) -> None:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute("DELETE FROM chunks WHERE doc_id=%s", (doc_id,))
                cursor.execute("DELETE FROM documents WHERE doc_id=%s", (doc_id,))
            self._conn.commit()

    # ---------- retrieval ----------

    def search(
        self,
        query_text: str,
        query_vector: list[float],
        *,
        limit: int = 6,
        course: str | None = None,
        doc_id: str | None = None,
    ) -> SearchResult:
        channel_limit = min(max(limit * 3, 8), 50)
        filters = ""
        filter_params: list[Any] = []
        if course:
            filters += " AND course = %s"
            filter_params.append(course)
        if doc_id:
            filters += " AND doc_id = %s"
            filter_params.append(doc_id)

        sql = f"""
        (SELECT 'fts' AS channel, chunk_id, doc_id, course, heading, page_no, ordinal,
                content, MATCH(content) AGAINST(%s) AS fts_score, NULL AS distance
         FROM chunks
         WHERE MATCH(content) AGAINST(%s){filters}
         ORDER BY fts_score DESC
         LIMIT %s)
        UNION ALL
        (SELECT 'vector' AS channel, chunk_id, doc_id, course, heading, page_no, ordinal,
                content, NULL AS fts_score, l2_distance(embedding, %s) AS distance
         FROM chunks
         WHERE 1=1{filters}
         ORDER BY l2_distance(embedding, %s) APPROXIMATE
         LIMIT %s)
        """
        vector_param = vector_literal(query_vector)
        params = (
            [query_text, query_text, *filter_params, channel_limit]
            + [vector_param, *filter_params, vector_param, channel_limit]
        )

        total_chunks = self.chunk_count()
        rows: list[dict[str, Any]] = []
        attempts = 6
        for attempt in range(attempts):
            with self._lock:
                with self._conn.cursor() as cursor:
                    cursor.execute(sql, tuple(params))
                    rows = list(cursor.fetchall())
            vector_hits = [row for row in rows if row["channel"] == "vector"]
            if vector_hits or total_chunks == 0 or attempt == attempts - 1:
                break
            time.sleep(0.25)

        raw_fts = sorted(
            (row for row in rows if row["channel"] == "fts"),
            key=lambda row: float(row["fts_score"] or 0.0),
            reverse=True,
        )
        raw_vector = sorted(
            (row for row in rows if row["channel"] == "vector"),
            key=lambda row: float(row["distance"] or 0.0),
        )

        # 两路候选都做相对阈值过滤，避免把明显无关的远端向量带进回答。
        fts_rows = raw_fts
        if raw_fts:
            best_fts = float(raw_fts[0]["fts_score"] or 0.0)
            if best_fts > 0:
                fts_rows = [
                    row for row in raw_fts if float(row["fts_score"] or 0.0) >= best_fts * 0.25
                ]
        vector_rows = raw_vector
        if raw_vector:
            best_distance = float(raw_vector[0]["distance"] or 0.0)
            vector_rows = [
                row
                for row in raw_vector
                if float(row["distance"] or 0.0) <= best_distance + 0.45
            ]

        fused = fuse_rankings(fts_rows, vector_rows, limit=limit)
        evidence = self._build_evidence(fused)
        trace = {
            "channels": {"fulltext": len(raw_fts), "vector": len(raw_vector)},
            "retained": {"fulltext": len(fts_rows), "vector": len(vector_rows)},
            "candidates": len(rows),
            "channel_limit": channel_limit,
            "attempts": attempt + 1,
            "precision_filter": {"vector_margin": 0.45, "fts_ratio": 0.25},
        }
        return SearchResult(evidence=evidence, trace=trace)

    def _build_evidence(self, fused: list[dict[str, Any]]) -> list[Evidence]:
        doc_ids = sorted({item["doc_id"] for item in fused})
        documents: dict[str, dict[str, Any]] = {}
        if doc_ids:
            placeholders = ",".join(["%s"] * len(doc_ids))
            with self._lock:
                with self._conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT doc_id, title, source FROM documents "
                        f"WHERE doc_id IN ({placeholders})",
                        tuple(doc_ids),
                    )
                    documents = {row["doc_id"]: row for row in cursor.fetchall()}

        evidence: list[Evidence] = []
        for item in fused:
            document = documents.get(item["doc_id"], {})
            evidence.append(
                Evidence(
                    chunk_id=item["chunk_id"],
                    doc_id=item["doc_id"],
                    course=item["course"],
                    heading=item["heading"],
                    page_no=item["page_no"],
                    content=item["content"],
                    title=document.get("title", item["doc_id"]),
                    source=document.get("source", ""),
                    fts_rank=item.get("fts_rank"),
                    vector_rank=item.get("vector_rank"),
                    fts_score=round(float(item["fts_score"]), 4)
                    if item.get("fts_score") is not None
                    else None,
                    distance=round(float(item["distance"]), 4)
                    if item.get("distance") is not None
                    else None,
                    score=float(item.get("score", 0.0)),
                )
            )
        return evidence

    # ---------- inventory ----------

    def documents(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "SELECT doc_id, course, title, source, license, tags, path, "
                    "chunk_count, ingested_at FROM documents ORDER BY course, title"
                )
                return list(cursor.fetchall())

    def courses(self) -> list[str]:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT DISTINCT course FROM documents ORDER BY course")
                return [row["course"] for row in cursor.fetchall()]

    def chunk_count(self) -> int:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM chunks")
                return int(cursor.fetchone()["total"])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM documents")
                document_count = int(cursor.fetchone()["total"])
                cursor.execute("SELECT COUNT(*) AS total FROM chunks")
                chunk_count = int(cursor.fetchone()["total"])
                cursor.execute(
                    "SELECT course, COUNT(*) AS documents, SUM(chunk_count) AS chunks "
                    "FROM documents GROUP BY course ORDER BY course"
                )
                courses = [
                    {
                        "course": row["course"],
                        "documents": int(row["documents"]),
                        "chunks": int(row["chunks"] or 0),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute("SELECT COUNT(*) AS total FROM qa_log")
                ask_count = int(cursor.fetchone()["total"])
        return {
            "documents": document_count,
            "chunks": chunk_count,
            "asks": ask_count,
            "courses": courses,
        }

    # ---------- qa log & sessions ----------

    def log_qa(
        self,
        *,
        session_id: str,
        question: str,
        course: str | None,
        top_k: int,
        chunk_ids: list[str],
        answer_mode: str,
        latency_ms: int,
    ) -> str:
        qa_id = f"qa_{uuid.uuid4().hex[:16]}"
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qa_log
                      (qa_id, session_id, question, course, top_k, chunk_ids,
                       answer_mode, latency_ms, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        qa_id,
                        session_id,
                        question,
                        course,
                        top_k,
                        json.dumps(chunk_ids, ensure_ascii=False),
                        answer_mode,
                        latency_ms,
                        utc_now(),
                    ),
                )
            self._conn.commit()
        return qa_id

    def history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "SELECT qa_id, question, course, top_k, chunk_ids, answer_mode, "
                    "latency_ms, created_at FROM qa_log WHERE session_id=%s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (session_id, limit),
                )
                rows = list(cursor.fetchall())
        for row in rows:
            try:
                row["chunk_ids"] = json.loads(row["chunk_ids"])
            except (TypeError, ValueError):
                row["chunk_ids"] = []
        return rows

    def get_session_scope(self, session_id: str) -> str | None:
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "SELECT scope_id FROM sessions WHERE session_id=%s", (session_id,)
                )
                row = cursor.fetchone()
        return row["scope_id"] if row else None

    def save_session_scope(self, session_id: str, scope_id: str, title: str) -> None:
        now = utc_now()
        with self._lock:
            with self._conn.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))
                cursor.execute(
                    "INSERT INTO sessions (session_id, scope_id, title, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (session_id, scope_id, title, now, now),
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            finally:
                self._instance.close()
