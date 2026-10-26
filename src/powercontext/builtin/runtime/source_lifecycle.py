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

"""Caller-declared evidence dependencies and their source availability.

Each Scope owns one acyclic graph. Registrations name only already-registered
parents, so stored ordinals are a topological order and one forward pass
propagates availability through every all/any policy. Source events are the
only inputs; derived nodes never receive events.

Memory availability is synchronized through the existing native deactivate /
reactivate writes. Topic availability is retained here and consulted by Topic
Memory search, which is what Context assembly also uses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory.errors import MemoryLayerError
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODES_TABLE,
)
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.errors import ArtifactError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime

_MAX_NODE_ID_LENGTH = 256
_MAX_REASON_LENGTH = 1024
_LifecyclePolicy = Literal["all", "any"]
_ResolvePurpose = Literal["generation", "audit"]


class SourceLifecycleError(ValueError):
    """A lifecycle registration, event, or resolution violated the contract."""


class SourceLifecycleEvent(BaseModel):
    """One Source availability transition at an exact lifecycle revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-blank string")  # noqa: TRY003
        return value


@dataclass(frozen=True, slots=True)
class _LifecycleNode:
    node_id: str
    kind: str
    reference: dict[str, object]
    revision: int | None
    parents: tuple[str, ...]
    policy: str | None
    ordinal: int
    available: bool
    last_sequence: int | None
    last_available: bool | None


def _encode_reference(reference: BaseModel) -> bytes:
    return json.dumps(
        reference.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _decode_reference(payload: bytes | bytearray | memoryview, kind: str) -> SourceRef | MemoryCitation | ArtifactRef:
    try:
        value = json.loads(bytes(payload))
    except (TypeError, ValueError) as error:
        raise SourceLifecycleError("registered reference is unreadable") from error
    if not isinstance(value, dict):
        raise SourceLifecycleError("registered reference is unreadable")
    return _decode_reference_value(value, kind)


def _decode_reference_value(
    value: dict[str, object],
    kind: str,
) -> SourceRef | MemoryCitation | ArtifactRef:
    try:
        if kind == "source":
            return SourceRef.model_validate(value)
        if kind == "memory":
            return MemoryCitation.model_validate(value)
        if kind == "topic":
            return ArtifactRef.model_validate(value)
    except ValueError as error:
        raise SourceLifecycleError("registered reference is unreadable") from error
    raise SourceLifecycleError("registered reference has an unknown kind")


def _node(row: dict[str, object]) -> _LifecycleNode:
    try:
        parents = json.loads(cast(str, row["parents"]))
        reference = json.loads(bytes(cast(bytes, row["reference"])))
    except (TypeError, ValueError) as error:
        raise SourceLifecycleError("registered node is unreadable") from error
    if not isinstance(parents, list) or not all(isinstance(item, str) for item in parents):
        raise SourceLifecycleError("registered parents are unreadable")
    if not isinstance(reference, dict):
        raise SourceLifecycleError("registered reference is unreadable")
    return _LifecycleNode(
        node_id=cast(str, row["node_id"]),
        kind=cast(str, row["kind"]),
        reference=reference,
        revision=cast(int | None, row["revision"]),
        parents=tuple(parents),
        policy=cast(str | None, row["policy"]),
        ordinal=cast(int, row["ordinal"]),
        available=bool(row["available"]),
        last_sequence=cast(int | None, row["last_sequence"]),
        last_available=cast(bool | None, row["last_available"]),
    )


def _require_node_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_NODE_ID_LENGTH:
        raise SourceLifecycleError("node_id")
    return value


def _require_positive_integer(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise SourceLifecycleError(name)
    return value


def _require_policy(value: object) -> _LifecyclePolicy:
    if value not in ("all", "any"):
        raise SourceLifecycleError("policy")
    return cast(_LifecyclePolicy, value)


def _require_parents(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise SourceLifecycleError("parents")
    parents = tuple(_require_node_id(item) for item in value)
    if not parents:
        raise SourceLifecycleError("parents")
    if len(set(parents)) != len(parents):
        raise SourceLifecycleError("parents")
    return parents


class ScopedSourceLifecycle:
    """Register dependencies and propagate Source events inside one Scope."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None, scope_id: str) -> None:
        self._runtime = runtime
        self._database = database
        self.scope_id = validate_scope_id(scope_id)

    @property
    def _required_database(self) -> AsyncDatabase:
        if self._database is None:
            raise SourceLifecycleError("source lifecycle persistence is not configured")
        return self._database

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        node = _require_node_id(node_id)
        revision = _require_positive_integer("revision", revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source_ref")
        await self._require_readable_source(source_ref)
        async with self._runtime._context(self.scope_id):
            async with self._runtime._locked(self.scope_id):
                await self._register(
                    node,
                    kind="source",
                    reference=source_ref,
                    revision=revision,
                    parents=(),
                    policy=None,
                )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        node = _require_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("citation")
        parent_ids = _require_parents(parents)
        selected_policy = _require_policy(policy)
        self._require_acyclic(node, parent_ids)
        await self._require_readable_memory(citation)
        async with self._runtime._context(self.scope_id):
            async with self._runtime._locked(self.scope_id):
                await self._register(
                    node,
                    kind="memory",
                    reference=citation,
                    revision=None,
                    parents=parent_ids,
                    policy=selected_policy,
                )
                # Idempotent registration still retries a previously
                # interrupted native-state write.
                await self._synchronize_memory()

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        /,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        node = _require_node_id(node_id)
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("artifact_ref")
        parent_ids = _require_parents(parents)
        selected_policy = _require_policy(policy)
        self._require_acyclic(node, parent_ids)
        await self._require_readable_artifact(artifact_ref)
        async with self._runtime._context(self.scope_id):
            async with self._runtime._locked(self.scope_id):
                await self._register(
                    node,
                    kind="topic",
                    reference=artifact_ref,
                    revision=None,
                    parents=parent_ids,
                    policy=selected_policy,
                )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event")
        database = self._required_database
        async with self._runtime._context(self.scope_id):
            async with self._runtime._locked(self.scope_id):
                async with database.transaction() as connection:
                    nodes = await self._load_nodes(connection, for_update=True)
                    by_id = {node.node_id: node for node in nodes}
                    source = by_id.get(event.node_id)
                    if source is None or source.kind != "source":
                        raise SourceLifecycleError("unknown source")
                    if source.revision != event.revision:
                        raise SourceLifecycleError("revision mismatch")
                    if source.last_sequence is not None:
                        if event.sequence < source.last_sequence:
                            raise SourceLifecycleError("stale sequence")
                        if event.sequence == source.last_sequence and event.available != source.last_available:
                            raise SourceLifecycleError("conflicting replay")
                    accepted = source.last_sequence is None or event.sequence > source.last_sequence
                    if accepted:
                        table = SOURCE_LIFECYCLE_NODES_TABLE
                        await connection.execute(
                            update(table)
                            .where(table.c.scope_id == self.scope_id, table.c.node_id == event.node_id)
                            .values(
                                available=event.available,
                                last_sequence=event.sequence,
                                last_available=event.available,
                            )
                        )
                        await connection.execute(
                            insert(SOURCE_LIFECYCLE_EVENTS_TABLE).values(
                                scope_id=self.scope_id,
                                node_id=event.node_id,
                                sequence=event.sequence,
                                revision=event.revision,
                                available=event.available,
                                reason=event.reason[:_MAX_REASON_LENGTH],
                            )
                        )
                    states = {node.node_id: node.available for node in nodes if node.kind == "source"}
                    if accepted:
                        states[event.node_id] = event.available
                    for node in nodes:
                        if node.kind == "source":
                            continue
                        support = [states[parent] for parent in node.parents]
                        values = all(support) if node.policy == "all" else any(support)
                        states[node.node_id] = values
                        if values != node.available:
                            table = SOURCE_LIFECYCLE_NODES_TABLE
                            await connection.execute(
                                update(table)
                                .where(table.c.scope_id == self.scope_id, table.c.node_id == node.node_id)
                                .values(available=values)
                            )
                await self._synchronize_memory()
        return sorted(node_id for node_id, available in states.items() if available)

    async def resolve(self, node_id: str, /, *, purpose: str) -> SourceRef | MemoryCitation | ArtifactRef:
        node = _require_node_id(node_id)
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("purpose")
        database = self._required_database
        async with database.transaction() as connection:
            stored = await self._load_node(connection, node)
        if stored is None:
            raise SourceLifecycleError("unknown node")
        if purpose == "generation" and not stored.available:
            raise SourceLifecycleError("node is unavailable for generation")
        return _decode_reference_value(stored.reference, stored.kind)

    async def hidden_topic_artifact_ids(self) -> frozenset[str]:
        """Return topic identities with no currently available lifecycle node."""

        database = self._required_database
        table = SOURCE_LIFECYCLE_NODES_TABLE
        async with database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(table.c.reference, table.c.available).where(
                        table.c.scope_id == self.scope_id,
                        table.c.kind == "topic",
                    )
                )
            ).all()
        support: dict[str, bool] = {}
        for payload, available in rows:
            try:
                reference = _decode_reference(cast(bytes, payload), "topic")
            except SourceLifecycleError:
                continue
            artifact_id = cast(ArtifactRef, reference).artifact_id
            support[artifact_id] = support.get(artifact_id, False) or bool(available)
        return frozenset(artifact_id for artifact_id, visible in support.items() if not visible)

    def _require_acyclic(self, node_id: str, parents: tuple[str, ...]) -> None:
        if node_id in parents:
            raise SourceLifecycleError("cycle")

    async def _register(
        self,
        node_id: str,
        *,
        kind: str,
        reference: BaseModel,
        revision: int | None,
        parents: tuple[str, ...],
        policy: _LifecyclePolicy | None,
    ) -> bool:
        database = self._required_database
        encoded = _encode_reference(reference)
        async with database.transaction() as connection:
            table = SOURCE_LIFECYCLE_NODES_TABLE
            rows = await self._load_nodes(connection, for_update=True)
            by_id = {node.node_id: node for node in rows}
            existing = by_id.get(node_id)
            if existing is not None:
                if (
                    existing.kind != kind
                    or existing.reference != json.loads(encoded)
                    or existing.revision != revision
                    or existing.parents != parents
                    or existing.policy != policy
                ):
                    raise SourceLifecycleError("node binding conflict")
                return False
            previous_ordinal = await connection.scalar(
                select(func.max(table.c.ordinal)).where(table.c.scope_id == self.scope_id)
            )
            for parent in parents:
                if parent not in by_id:
                    raise SourceLifecycleError("unknown parent")
            states = {node.node_id: node.available for node in rows}
            if kind == "source":
                available = True
            else:
                support = [states[parent] for parent in parents]
                available = all(support) if policy == "all" else any(support)
            await connection.execute(
                insert(table).values(
                    scope_id=self.scope_id,
                    node_id=node_id,
                    kind=kind,
                    reference=encoded,
                    revision=revision,
                    parents=json.dumps(parents, separators=(",", ":")),
                    policy=policy,
                    ordinal=0 if previous_ordinal is None else int(previous_ordinal) + 1,
                    available=available,
                )
            )
        return True

    async def _load_nodes(self, connection: AsyncConnection, *, for_update: bool = False) -> tuple[_LifecycleNode, ...]:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        statement = (
            select(table)
            .where(table.c.scope_id == self.scope_id)
            .order_by(table.c.ordinal)
        )
        if for_update:
            statement = statement.with_for_update()
        rows = (await connection.execute(statement)).mappings()
        return tuple(_node(dict(row)) for row in rows)

    async def _load_node(self, connection: AsyncConnection, node_id: str) -> _LifecycleNode | None:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        row = (
            (
                await connection.execute(
                    select(table).where(table.c.scope_id == self.scope_id, table.c.node_id == node_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _node(dict(row))

    async def _require_readable_source(self, source_ref: SourceRef) -> None:
        try:
            await self._runtime._records().get_source(
                self.scope_id, source_ref.source_type, source_ref.source_id
            )
        except Exception as error:
            raise SourceLifecycleError("source reference is not readable") from error

    async def _require_readable_memory(self, citation: MemoryCitation) -> None:
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            try:
                await service.revision(citation.memory_ref)
                await service.validate_citation(citation)
            except (ArtifactError, MemoryLayerError) as error:
                raise SourceLifecycleError("memory reference is not readable") from error

    async def _require_readable_artifact(self, artifact_ref: ArtifactRef) -> None:
        try:
            await self._runtime._records().get_artifact_revision(
                self.scope_id,
                artifact_ref.family,
                artifact_ref.artifact_id,
                artifact_ref.revision,
            )
        except Exception as error:
            raise SourceLifecycleError("artifact reference is not readable") from error

    async def _synchronize_memory(self) -> None:
        """Apply the graph's Memory state through native deactivate / reactivate.

        The caller already holds this Scope's write lock. Comparing the native
        manifest state first makes event replay and retries revision-free.
        """

        database = self._required_database
        table = SOURCE_LIFECYCLE_NODES_TABLE
        async with database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(table.c.reference, table.c.available)
                    .where(table.c.scope_id == self.scope_id, table.c.kind == "memory")
                    .order_by(table.c.ordinal)
                )
            ).all()
        if not rows:
            return
        # One body entry can back several nodes; it stays active while any of
        # them retains support.
        citations: dict[tuple[str, str], MemoryCitation] = {}
        desired: dict[tuple[str, str], bool] = {}
        for payload, available in rows:
            citation = cast(MemoryCitation, _decode_reference(cast(bytes, payload), "memory"))
            key = (citation.memory_ref.artifact_id, citation.entry_id)
            citations.setdefault(key, citation)
            desired[key] = desired.get(key, False) or bool(available)
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            for citation in citations.values():
                available = desired[(citation.memory_ref.artifact_id, citation.entry_id)]
                try:
                    memory = await service.head(citation.memory_ref.artifact_id)
                except ArtifactError as error:
                    raise SourceLifecycleError("memory reference is no longer readable") from error
                manifest = next(
                    (item for item in memory.content.manifest.entries if item.entry_id == citation.entry_id),
                    None,
                )
                if manifest is None:
                    raise SourceLifecycleError("memory entry is no longer present")
                entry = next(
                    (item for item in await service.entries(memory) if item.entry_id == citation.entry_id),
                    None,
                )
                if entry is None:
                    raise SourceLifecycleError("memory entry is no longer readable")
                target_state = "active" if available else "inactive"
                if manifest.state == target_state:
                    continue
                if target_state == "active":
                    await service.reactivate(memory, entries=(entry,), reason="source lifecycle restore")
                else:
                    await service.forget(memory, entries=(entry,), reason="source lifecycle withdrawal")


class SourceLifecycleApplication:
    """Select a scoped source-lifecycle service."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None) -> None:
        self._runtime = runtime
        self._database = database

    @property
    def configured(self) -> bool:
        return self._database is not None

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, self._database, scope_id)


__all__ = [
    "ScopedSourceLifecycle",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
