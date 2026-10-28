"""PowerContext 任务状态：scope、写入、检索与重启后读取。"""

from __future__ import annotations

from typing import Any

import httpx


class StateUnavailable(RuntimeError):
    """PowerContext 不可用。任务状态必须持久化，禁止静默降级。"""


class PowerContextState:
    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PowerContextState:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StateUnavailable(
                f"无法连接 PowerContext（{self.base_url}）：{exc.__class__.__name__}"
            ) from exc
        if response.status_code >= 400:
            raise StateUnavailable(
                f"PowerContext 返回 {response.status_code}：{response.text[:300]}"
            )
        return response.json() if response.content else {}

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
            "GET", "/v1/scopes", params={"query": title, "query_field": "title"}
        )
        for item in payload.get("items", []):
            if item.get("title") == title:
                return item["scope_id"]
        return None

    def ensure_scope(self, task_id: str) -> str:
        title = f"SDD · {task_id}"
        scope_id = self.find_scope(title)
        if scope_id:
            return scope_id
        payload = self._request(
            "POST",
            "/v1/scopes",
            json={
                "title": title,
                "summary": "SDD 工程上下文任务：规格、代码、测试与验证进度。",
                "idempotency_key": f"sdd-scope-{task_id}",
            },
        )
        return payload["scope_id"]

    def remember(
        self, scope_id: str, text: str, *, kind: str, reason: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/memory/remember",
            json={"scope_id": scope_id, "kind": kind, "text": text, "reason": reason},
        )

    def search(self, scope_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        payload = self._request(
            "POST",
            "/v1/memory/search",
            json={"scope_id": scope_id, "query": query, "limit": limit, "mode": "auto"},
        )
        return list(payload.get("hits", []))

    def list_entries(self, scope_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "POST", "/v1/memory/entries/list", json={"scope_id": scope_id}
        )
        return list(payload.get("entries", []))

    def status(self, task_id: str) -> dict[str, Any]:
        scope_id = self.ensure_scope(task_id)
        entries = self.list_entries(scope_id)
        buckets: dict[str, list[str]] = {"todo": [], "done": [], "verified": []}
        for entry in entries:
            kind = str(entry.get("kind") or "note")
            text = str(entry.get("text") or "")
            if kind in buckets:
                buckets[kind].append(text)
        return {
            "available": True,
            "scope_id": scope_id,
            "todo": buckets["todo"],
            "done": buckets["done"],
            "verified": buckets["verified"],
            "entry_count": len(entries),
        }
