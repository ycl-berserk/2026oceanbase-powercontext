from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class MemoryUnavailable(RuntimeError):
    """PowerContext 不可用时抛出，调用方可以降级为无记忆模式。"""


@dataclass
class MemoryHit:
    entry_id: str
    text: str
    kind: str
    score: float
    matched_by: list[str]
    citation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "text": self.text,
            "kind": self.kind,
            "score": round(self.score, 4),
            "matched_by": self.matched_by,
        }


class PowerContextMemory:
    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise MemoryUnavailable(
                f"无法连接 PowerContext（{self.base_url}）：{exc.__class__.__name__}"
            ) from exc
        if response.status_code >= 400:
            detail = response.text[:300]
            raise MemoryUnavailable(
                f"PowerContext 返回 {response.status_code}：{detail}"
            )
        if not response.content:
            return {}
        return response.json()

    def health(self) -> dict[str, Any]:
        live = self._request("GET", "/health/live")
        ready = self._request("GET", "/health/ready")
        return {
            "url": self.base_url,
            "alive": live.get("status") == "ok",
            "ready": ready.get("status") == "ready",
        }

    def find_scope(self, title: str) -> str | None:
        payload = self._request(
            "GET",
            "/v1/scopes",
            params={"query": title, "query_field": "title"},
        )
        for item in payload.get("items", []):
            if item.get("title") == title:
                return item["scope_id"]
        return None

    def ensure_scope(self, session_id: str) -> tuple[str, str]:
        title = f"温故 ReviewMate · {session_id}"
        summary = "课程笔记复习助手：保存薄弱点、复习进度与提问记录。"
        scope_id = self.find_scope(title)
        if scope_id:
            return scope_id, title
        try:
            payload = self._request(
                "POST",
                "/v1/scopes",
                json={
                    "title": title,
                    "summary": summary,
                    "idempotency_key": f"reviewmate-scope-{session_id}",
                },
            )
        except MemoryUnavailable:
            scope_id = self.find_scope(title)
            if scope_id:
                return scope_id, title
            raise
        return payload["scope_id"], title

    def remember(
        self,
        scope_id: str,
        text: str,
        *,
        kind: str = "study-note",
        reason: str | None = None,
    ) -> MemoryHit:
        payload = self._request(
            "POST",
            "/v1/memory/remember",
            json={"scope_id": scope_id, "kind": kind, "text": text, "reason": reason},
        )
        entry = payload.get("entry") or {}
        if not entry:
            # PowerContext 会去重：重复写入返回 entry=null，此时回查已有条目。
            for existing in self.list_entries(scope_id):
                if existing.text == text:
                    return existing
        citation = entry.get("citation") or {}
        return MemoryHit(
            entry_id=citation.get("entry_id", ""),
            text=entry.get("text", text),
            kind=entry.get("kind", kind),
            score=1.0,
            matched_by=["remember"],
            citation=citation,
        )

    def search(self, scope_id: str, query: str, limit: int = 5) -> list[MemoryHit]:
        payload = self._request(
            "POST",
            "/v1/memory/search",
            json={"scope_id": scope_id, "query": query, "limit": limit, "mode": "auto"},
        )
        hits: list[MemoryHit] = []
        for item in payload.get("hits", []):
            citation = item.get("citation") or {}
            hits.append(
                MemoryHit(
                    entry_id=citation.get("entry_id", ""),
                    text=item.get("text", ""),
                    kind="memory",
                    score=float(item.get("score") or 0.0),
                    matched_by=list(item.get("matched_by") or []),
                    citation=citation,
                )
            )
        return hits

    def list_entries(self, scope_id: str, *, include_inactive: bool = False) -> list[MemoryHit]:
        payload = self._request(
            "POST",
            "/v1/memory/entries/list",
            json={"scope_id": scope_id, "include_inactive": include_inactive},
        )
        entries: list[MemoryHit] = []
        for item in payload.get("entries", []):
            entries.append(
                MemoryHit(
                    entry_id=(item.get("citation") or {}).get("entry_id", ""),
                    text=item.get("text", ""),
                    kind=item.get("kind", "memory"),
                    score=1.0,
                    matched_by=["list"],
                    citation=item.get("citation") or {},
                )
            )
        return entries

    def retire(self, scope_id: str, citation: dict[str, Any], reason: str = "用户删除") -> None:
        self._request(
            "POST",
            "/v1/memory/entries/retire",
            json={"scope_id": scope_id, "citation": citation, "reason": reason},
        )
