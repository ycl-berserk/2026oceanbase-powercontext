"""seekdb 存储：规格、代码符号与测试的索引和全文检索。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymysql
import pylibseekdb as seekdb

SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS eng_docs (
      doc_key VARCHAR(191) PRIMARY KEY,
      kind VARCHAR(16) NOT NULL,
      path VARCHAR(512) NOT NULL,
      symbol VARCHAR(191) NOT NULL,
      heading VARCHAR(255) NOT NULL,
      content TEXT NOT NULL,
      start_line INT NOT NULL,
      end_line INT NOT NULL,
      FULLTEXT INDEX ft_eng_content (content) WITH PARSER NGRAM
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS ingest_meta (
      meta_key VARCHAR(64) PRIMARY KEY,
      meta_value VARCHAR(255) NOT NULL
    ) ORGANIZATION = HEAP
    """,
)

COLUMNS = "doc_key, kind, path, symbol, heading, content, start_line, end_line"


@dataclass(frozen=True)
class Doc:
    doc_key: str
    kind: str
    path: str
    symbol: str
    heading: str
    content: str
    start_line: int
    end_line: int


class Store:
    """嵌入式 seekdb，进程内打开，不需要独立服务。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._instance = seekdb.open(str(self.db_path))
        options = dict(self._instance.connection_options())
        options.setdefault("database", "test")
        options["cursorclass"] = pymysql.cursors.DictCursor
        options["autocommit"] = False
        self._conn = pymysql.connect(**options)
        self._ensure_schema()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn.cursor() as cursor:
            for statement in SCHEMA:
                cursor.execute(statement)
            self._conn.commit()

    def clear(self) -> None:
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute("DELETE FROM eng_docs")
            cursor.execute("DELETE FROM ingest_meta")
            self._conn.commit()

    def upsert(self, docs: list[Doc]) -> None:
        if not docs:
            return
        rows = [
            (
                doc.doc_key,
                doc.kind,
                doc.path,
                doc.symbol,
                doc.heading,
                doc.content,
                doc.start_line,
                doc.end_line,
            )
            for doc in docs
        ]
        placeholders = ", ".join(["%s"] * 8)
        statement = f"REPLACE INTO eng_docs ({COLUMNS}) VALUES ({placeholders})"
        with self._lock, self._conn.cursor() as cursor:
            for row in rows:
                cursor.execute(statement, row)
            self._conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "REPLACE INTO ingest_meta (meta_key, meta_value) VALUES (%s, %s)",
                (key, value),
            )
            self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT meta_value FROM ingest_meta WHERE meta_key = %s", (key,)
            )
            row = cursor.fetchone()
        return row["meta_value"] if row else None

    def stats(self) -> dict[str, int]:
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute("SELECT kind, COUNT(*) AS total FROM eng_docs GROUP BY kind")
            rows = cursor.fetchall() or []
        return {row["kind"]: int(row["total"]) for row in rows}

    def search(self, kind: str, query: str, limit: int = 4) -> list[dict[str, Any]]:
        statement = (
            "SELECT doc_key, kind, path, symbol, heading, start_line, end_line, "
            "MATCH(content) AGAINST(%s) AS score "
            "FROM eng_docs WHERE kind = %s AND MATCH(content) AGAINST(%s) "
            "ORDER BY score DESC, doc_key ASC LIMIT %s"
        )
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(statement, (query, kind, query, int(limit)))
            rows = cursor.fetchall() or []
        for row in rows:
            row["score"] = round(float(row.get("score") or 0.0), 6)
        return list(rows)

    def get(self, doc_key: str) -> dict[str, Any] | None:
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {COLUMNS} FROM eng_docs WHERE doc_key = %s", (doc_key,)
            )
            return cursor.fetchone()
