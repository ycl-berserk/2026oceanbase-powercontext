from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunking import ParsedDocument, parse_document
from .config import Settings
from .embeddings import Embedder
from .llm import AnswerWriter, GeneratedText
from .memory import MemoryHit, MemoryUnavailable, PowerContextMemory
from .store import Evidence, SeekDBStore

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class AskResult:
    qa_id: str
    question: str
    course: str | None
    answer: str
    answer_mode: str
    citations: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    memory_status: dict[str, Any]
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "qa_id": self.qa_id,
            "question": self.question,
            "course": self.course,
            "answer": self.answer,
            "answer_mode": self.answer_mode,
            "citations": self.citations,
            "memories": self.memories,
            "memory_status": self.memory_status,
            "trace": self.trace,
        }


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class ReviewMateService:
    def __init__(
        self,
        settings: Settings,
        *,
        store: SeekDBStore | None = None,
        embedder: Embedder | None = None,
        memory: PowerContextMemory | None = None,
        writer: AnswerWriter | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or SeekDBStore(
            settings.db_path,
            embed_dim=settings.embed_dim,
            embed_model=settings.embed_model,
        )
        self._embedder = embedder
        self.memory = memory or PowerContextMemory(
            settings.powercontext_url, timeout=settings.powercontext_timeout
        )
        self.writer = writer or AnswerWriter(settings)

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(
                self.settings.embed_model,
                cache_dir=self.settings.embed_cache,
                dim=self.settings.embed_dim,
            )
        return self._embedder

    # ---------- ingest ----------

    def ingest(
        self,
        paths: list[Path] | None = None,
        *,
        course_override: str | None = None,
    ) -> list[dict[str, Any]]:
        files = self._collect_files(paths)
        if not files:
            raise ValueError("没有找到可导入的资料（支持 .md / .markdown / .txt）")

        parsed: dict[str, ParsedDocument] = {}
        for path in files:
            document = parse_document(path, course_override=course_override)
            parsed[document.doc_id] = document

        results: list[dict[str, Any]] = []
        for document in parsed.values():
            vectors = self.embedder.embed_documents(
                [chunk.embed_text for chunk in document.chunks]
            )
            summary = self.store.upsert_document(document, vectors)
            summary["path"] = document.path
            results.append(summary)
        return results

    def ingest_samples(self) -> list[dict[str, Any]]:
        return self.ingest([self.settings.samples_dir])

    @staticmethod
    def _collect_files(paths: list[Path] | None) -> list[Path]:
        if not paths:
            return []
        files: list[Path] = []
        for path in paths:
            path = Path(path)
            if path.is_dir():
                files.extend(
                    sorted(
                        item
                        for item in path.rglob("*")
                        if item.is_file() and item.suffix.lower() in {".md", ".markdown", ".txt"}
                    )
                )
            elif path.is_file():
                files.append(path)
            else:
                raise FileNotFoundError(f"资料路径不存在：{path}")
        return files

    # ---------- ask ----------

    def ask(
        self,
        question: str,
        *,
        session_id: str = "demo",
        course: str | None = None,
        top_k: int | None = None,
    ) -> AskResult:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空")
        session_id = self.normalize_session(session_id)
        limit = max(1, min(top_k or self.settings.top_k, 20))
        started = time.perf_counter()

        t0 = time.perf_counter()
        query_vector = self.embedder.embed_query(question)
        embed_ms = _elapsed_ms(t0)

        t0 = time.perf_counter()
        retrieval = self.store.search(
            question, query_vector, limit=limit, course=course or None
        )
        retrieval_ms = _elapsed_ms(t0)

        t0 = time.perf_counter()
        memories, memory_status = self._memory_context(session_id, question)
        if memory_status["available"]:
            memory_status.update(
                self._remember_ask(
                    memory_status["scope_id"], question, course, retrieval.evidence
                )
            )
        memory_ms = _elapsed_ms(t0)

        t0 = time.perf_counter()
        generated = self.writer.answer(question, retrieval.evidence, memories, course)
        answer_ms = _elapsed_ms(t0)

        used_ids = set(generated.used_chunk_ids)
        citations = [
            {"index": index, **item.to_dict(), "used": item.chunk_id in used_ids}
            for index, item in enumerate(retrieval.evidence, start=1)
        ]
        qa_id = self.store.log_qa(
            session_id=session_id,
            question=question,
            course=course,
            top_k=limit,
            chunk_ids=[item.chunk_id for item in retrieval.evidence],
            answer_mode=generated.mode,
            latency_ms=_elapsed_ms(started),
        )

        trace = {
            "embedding_model": self.settings.embed_model,
            "embedding_dim": self.settings.embed_dim,
            "top_k": limit,
            "course": course,
            "retrieval": retrieval.trace,
            "timing_ms": {
                "embed": embed_ms,
                "retrieval": retrieval_ms,
                "memory": memory_ms,
                "answer": answer_ms,
                "total": _elapsed_ms(started),
            },
            "powercontext": memory_status,
            "llm": {"mode": generated.mode, "model": generated.model},
            "qa_id": qa_id,
        }
        if generated.warning:
            trace["llm"]["warning"] = generated.warning

        return AskResult(
            qa_id=qa_id,
            question=question,
            course=course,
            answer=generated.text,
            answer_mode=generated.mode,
            citations=citations,
            memories=[item.to_dict() for item in memories],
            memory_status=memory_status,
            trace=trace,
        )

    def _memory_context(
        self, session_id: str, question: str
    ) -> tuple[list[MemoryHit], dict[str, Any]]:
        try:
            scope_id = self._scope_for(session_id)
            hits = self.memory.search(scope_id, question, limit=5)
            return hits, {
                "available": True,
                "scope_id": scope_id,
                "hits": len(hits),
                "error": None,
            }
        except MemoryUnavailable as exc:
            return [], {
                "available": False,
                "scope_id": None,
                "hits": 0,
                "error": str(exc),
            }

    def _remember_ask(
        self,
        scope_id: str,
        question: str,
        course: str | None,
        evidence: list[Evidence],
    ) -> dict[str, Any]:
        titles: list[str] = []
        for item in evidence[:3]:
            if item.title and item.title not in titles:
                titles.append(item.title)
        note = f"提问：{question[:180]}"
        if course:
            note = f"{course}｜{note}"
        if titles:
            note += f"；参考：{'、'.join(titles)}"
        try:
            hit = self.memory.remember(
                scope_id,
                note,
                kind="study-progress",
                reason="ReviewMate 自动记录本次提问",
            )
            return {"recorded": True, "recorded_entry_id": hit.entry_id, "write_error": None}
        except MemoryUnavailable as exc:
            return {"recorded": False, "recorded_entry_id": None, "write_error": str(exc)}

    def _scope_for(self, session_id: str) -> str:
        scope_id = self.store.get_session_scope(session_id)
        if scope_id:
            return scope_id
        scope_id, title = self.memory.ensure_scope(session_id)
        self.store.save_session_scope(session_id, scope_id, title)
        return scope_id

    # ---------- memory ----------

    def mark_weak_point(
        self, session_id: str, topic: str, detail: str = ""
    ) -> dict[str, Any]:
        topic = topic.strip()
        if not topic:
            raise ValueError("薄弱点主题不能为空")
        session_id = self.normalize_session(session_id)
        text = f"薄弱点：{topic[:300]}"
        if detail.strip():
            text += f"。补充说明：{detail.strip()[:600]}"
        scope_id = self._scope_for(session_id)
        hit = self.memory.remember(
            scope_id,
            text,
            kind="weak-point",
            reason="用户在 ReviewMate 学习界面标记的薄弱点",
        )
        return {"scope_id": scope_id, "memory": hit.to_dict(), "text": text}

    def remember_note(self, session_id: str, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        session_id = self.normalize_session(session_id)
        scope_id = self._scope_for(session_id)
        hit = self.memory.remember(
            scope_id,
            text[:2000],
            kind="study-note",
            reason="用户手动写入的学习记忆",
        )
        return {"scope_id": scope_id, "memory": hit.to_dict(), "text": text}

    def memory_entries(self, session_id: str) -> dict[str, Any]:
        session_id = self.normalize_session(session_id)
        try:
            scope_id = self._scope_for(session_id)
            entries = self.memory.list_entries(scope_id)
            return {
                "available": True,
                "scope_id": scope_id,
                "entries": [item.to_dict() for item in entries],
                "error": None,
            }
        except MemoryUnavailable as exc:
            return {
                "available": False,
                "scope_id": None,
                "entries": [],
                "error": str(exc),
            }

    def weak_points(self, session_id: str) -> tuple[list[MemoryHit], dict[str, Any]]:
        payload = self.memory_entries(session_id)
        points = [
            MemoryHit(
                entry_id=item["entry_id"],
                text=item["text"],
                kind=item["kind"],
                score=item["score"],
                matched_by=item["matched_by"],
                citation={},
            )
            for item in payload["entries"]
            if item["kind"] == "weak-point"
        ]
        return points, payload

    # ---------- review plan ----------

    def review_plan(self, session_id: str, course: str | None = None) -> dict[str, Any]:
        session_id = self.normalize_session(session_id)
        weak_points, memory_payload = self.weak_points(session_id)
        documents = [
            item
            for item in self.store.documents()
            if not course or item["course"] == course
        ]
        generated = self.writer.plan(
            course=course, weak_points=weak_points, documents=documents
        )
        return {
            "plan": generated.text,
            "mode": generated.mode,
            "weak_points": [item.to_dict() for item in weak_points],
            "documents": documents,
            "powercontext": {
                "available": memory_payload["available"],
                "scope_id": memory_payload["scope_id"],
                "error": memory_payload["error"],
            },
        }

    # ---------- inventory ----------

    def documents(self) -> list[dict[str, Any]]:
        return self.store.documents()

    def courses(self) -> list[str]:
        return self.store.courses()

    def history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.history(self.normalize_session(session_id), limit)

    def health(self) -> dict[str, Any]:
        try:
            memory_health: dict[str, Any] = {"available": True, **self.memory.health()}
        except MemoryUnavailable as exc:
            memory_health = {"available": False, "error": str(exc)}
        try:
            database = self.store.stats()
            db_ready = True
            db_error = None
        except Exception as exc:  # noqa: BLE001 - 健康检查要报告而不是抛出
            database = {}
            db_ready = False
            db_error = str(exc)
        return {
            "status": "ok" if db_ready else "degraded",
            "seekdb": {
                "ready": db_ready,
                "db_path": str(self.settings.db_path),
                "error": db_error,
                **database,
            },
            "powercontext": memory_health,
            "embedding": {
                "model": self.settings.embed_model,
                "dim": self.settings.embed_dim,
                "loaded": self._embedder is not None,
            },
            "llm": {
                "mode": self.settings.llm_mode,
                "model": self.settings.deepseek_model
                if self.settings.llm_mode == "deepseek"
                else None,
            },
        }

    @staticmethod
    def normalize_session(session_id: str) -> str:
        value = (session_id or "demo").strip()
        if not SESSION_RE.match(value):
            raise ValueError("会话 ID 只能包含字母、数字、下划线和短横线，长度 1-64")
        return value

    def close(self) -> None:
        self.memory.close()
        self.store.close()


def build_service(settings: Settings | None = None) -> ReviewMateService:
    return ReviewMateService(settings or Settings.load())


def generated_summary(generated: GeneratedText) -> dict[str, Any]:
    return {"text": generated.text, "mode": generated.mode, "model": generated.model}
