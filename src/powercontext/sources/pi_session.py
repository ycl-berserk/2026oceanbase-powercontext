# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Capture the complete visible event history of one selected Pi session branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.connectors import (
    Connector,
    ConnectorBinding,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
)
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
_CHECKPOINT_VERSION = 1


class PiSessionInput(BaseModel):
    """One Pi v3 JSONL session archive and an optional selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch, with its complete source record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    """A captured Pi event addressed by its session and event identity."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Return a stable, collision-resistant identity for one session event."""

    if not isinstance(session_id, str) or not session_id or session_id != session_id.strip():
        raise ValueError("session_id must be a non-empty trimmed string")  # noqa: TRY003
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a non-empty string")  # noqa: TRY003
    identity = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(f"{session_id}\x00{event_id}".encode()).hexdigest()
        identity = f"pi:sha256:{digest}"
    return identity


def _decode_jsonl(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session archive must be valid UTF-8") from error
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi session archive contains invalid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("Pi session archive records must be JSON objects")  # noqa: TRY003
        records.append(value)
    if not records:
        raise ValueError("Pi session archive must contain a session header")  # noqa: TRY003
    return records


def _record_id(record: dict[str, Any], field: str = "id") -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Pi {field} must be a non-empty string")  # noqa: TRY003
    return value


def _text_blocks(content: object) -> list[str] | None:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            return None
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name")
            call_id = block.get("id")
            arguments = block.get("arguments", {})
            parts.append(
                f"[tool_call {name} {call_id}] "
                + json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
    return parts


def _event_content(record: dict[str, Any]) -> tuple[str, str] | None:
    event_type = record.get("type")
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role:
            return None
        if role == "bashExecution":
            command = message.get("command")
            output = message.get("output")
            body = f"$ {command or ''}\n{output or ''}"
        elif role == "toolResult":
            name = message.get("toolName")
            call_id = message.get("toolCallId")
            parts = _text_blocks(message.get("content")) or []
            body = f"[tool_result {name} {call_id}] " + "\n".join(parts)
        else:
            parts = _text_blocks(message.get("content"))
            if parts is None:
                return None
            body = "\n".join(parts)
        body = body.strip()
        if not body:
            return None
        return role, body
    if event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        return str(event_type), summary
    if event_type == "custom_message":
        parts = _text_blocks(record.get("content"))
        if parts is None:
            return None
        body = "\n".join(parts).strip()
        if not body:
            return None
        return "custom", body
    return None


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse the complete ancestor chain of the selected leaf into visible events."""

    records = _decode_jsonl(value.content)
    header = records[0]
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("Pi session header must be type=session version=3")  # noqa: TRY003
    session_id = _record_id(header)

    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records[1:]:
        event_id = _record_id(record)
        if event_id in nodes:
            raise ValueError("Pi session event ids must be unique")  # noqa: TRY003
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("Pi parentId must be null or a non-empty string")  # noqa: TRY003
            if parent_id == event_id or parent_id not in nodes:
                raise ValueError("Pi parentId must reference an earlier event")  # noqa: TRY003
        nodes[event_id] = record
        order.append(event_id)

    leaf_id = value.leaf_id
    if leaf_id is None:
        leaf_id = order[-1] if order else None
    elif leaf_id not in nodes:
        raise ValueError("Pi leaf_id does not identify an event")  # noqa: TRY003

    chain: list[str] = []
    current = leaf_id
    while current is not None:
        chain.append(current)
        current = nodes[current].get("parentId")
    chain.reverse()

    events: list[PiEventInput] = []
    for event_id in chain:
        record = nodes[event_id]
        parsed = _event_content(record)
        if parsed is None:
            continue
        role, content = parsed
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=event_id,
                parent_id=record.get("parentId"),
                event_type=str(record.get("type")),
                role=role,
                content=f"{role}: {content}",
                record=record,
            )
        )
    return tuple(events)


class PiEventAdapter:
    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=pi_event_source_id(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_ADAPTER = PiEventAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_ADAPTER,
    projections=(PiEventTextEvidenceProjection(),),
)


def _record_digest(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_checkpoint(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or value.get("version") != _CHECKPOINT_VERSION:
        raise ValueError("Pi connector checkpoint is invalid")  # noqa: TRY003
    events = value.get("events")
    if not isinstance(events, dict):
        raise ValueError("Pi connector checkpoint is invalid")  # noqa: TRY003
    loaded: dict[str, str] = {}
    for event_id, digest in events.items():
        if not isinstance(event_id, str) or not isinstance(digest, str):
            raise ValueError("Pi connector checkpoint is invalid")  # noqa: TRY003
        loaded[event_id] = digest
    return loaded


class PiSessionConnector(Connector):
    """Import only newly visible branch events while preserving durable progress."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(
            PiSessionInput(content=self._path.read_bytes(), leaf_id=self._leaf_id)
        )
        imported = _load_checkpoint(session.checkpoint)
        next_checkpoint = dict(imported)
        for event in events:
            digest = _record_digest(event.record)
            previous = imported.get(event.event_id)
            if previous is not None:
                if previous != digest:
                    raise ValueError(f"imported Pi event {event.event_id!r} was rewritten")  # noqa: TRY003
                continue
            outcome = await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            if outcome.source_ref is not None:
                next_checkpoint[event.event_id] = digest
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"version": _CHECKPOINT_VERSION, "events": next_checkpoint},
        )


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
