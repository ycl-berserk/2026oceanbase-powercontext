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

"""Compact, verifiable context packs and prefix-reusing deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DIGEST_PREFIX = "sha256:"
_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(ValueError):
    """A context pack or delta violated the wire contract."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: object) -> bytes:
    if not isinstance(value, str):
        raise ContextPackError("base64 items must be strings")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise ContextPackError("invalid base64 item") from error
    if _b64encode(decoded) != value:
        raise ContextPackError("base64 items must use canonical encoding")
    return decoded


def _digest_for(schema: str, items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": schema, "items": [_b64encode(item) for item in items]}
    return _DIGEST_PREFIX + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX) or len(value) != 71:
        raise ContextPackError(f"{field_name} must be a sha256 digest")
    hexadecimal = value[len(_DIGEST_PREFIX) :]
    if any(character not in "0123456789abcdef" for character in hexadecimal):
        raise ContextPackError(f"{field_name} must be lowercase hexadecimal")
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextPackError(f"{field_name} must be an integer")
    return value


def _require_exact_fields(payload: object, expected: frozenset[str], object_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContextPackError(f"{object_name} must be a JSON object")
    keys = frozenset(payload)
    if keys != expected:
        missing = expected - keys
        extra = keys - expected
        detail = []
        if missing:
            detail.append(f"missing {sorted(missing)}")
        if extra:
            detail.append(f"extra {sorted(extra)}")
        raise ContextPackError(f"{object_name} has invalid fields: {', '.join(detail)}")
    return payload


def _load_json(data: bytes) -> object:
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("invalid JSON encoding") from error


@dataclass(frozen=True, slots=True, eq=False)
class ContextPack:
    """A complete context represented as ordered, checksummed byte items."""

    items: tuple[bytes, ...]
    digest: str = field(init=False)
    byte_count: int = field(init=False)

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if any(not isinstance(item, bytes) for item in items):
            raise ContextPackError("pack items must be bytes")
        object.__setattr__(self, "items", items)
        digest = _digest_for(PACK_SCHEMA, items)
        object.__setattr__(self, "digest", digest)
        byte_count = 0
        while True:
            payload = {
                "schema": PACK_SCHEMA,
                "items": [_b64encode(item) for item in items],
                "digest": digest,
                "byte_count": byte_count,
            }
            encoded = _canonical(payload)
            if len(encoded) == byte_count:
                break
            byte_count = len(encoded)
        object.__setattr__(self, "byte_count", byte_count)

    @classmethod
    def build(cls, items: tuple[bytes, ...] | list[bytes]) -> ContextPack:
        return cls(tuple(items))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = 512) -> ContextPack:
        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        if not isinstance(text, str):
            raise ContextPackError("content must be text or UTF-8 bytes")
        if not text:
            return cls(())
        chunks: list[bytes] = []
        current = bytearray()
        for character in text:
            encoded = character.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("chunk_bytes is too small for one UTF-8 character")
            if current and len(current) + len(encoded) > chunk_bytes:
                chunks.append(bytes(current))
                current.clear()
            current.extend(encoded)
        if current:
            chunks.append(bytes(current))
        return cls(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _canonical(
            {
                "schema": PACK_SCHEMA,
                "items": [_b64encode(item) for item in self.items],
                "digest": self.digest,
                "byte_count": self.byte_count,
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _require_exact_fields(_load_json(data), _PACK_FIELDS, "context pack")
        if payload["schema"] != PACK_SCHEMA:
            raise ContextPackError("unsupported context pack schema")
        raw_items = payload["items"]
        if not isinstance(raw_items, list):
            raise ContextPackError("pack items must be a list")
        items = tuple(_b64decode(item) for item in raw_items)
        digest = _require_digest(payload["digest"], "digest")
        if digest != _digest_for(PACK_SCHEMA, items):
            raise ContextPackError("context pack digest does not match its items")
        byte_count = _require_int(payload["byte_count"], "byte_count")
        if byte_count != len(data):
            raise ContextPackError("context pack byte_count does not match its encoded size")
        pack = cls(items)
        if pack.digest != digest:
            raise ContextPackError("context pack digest is not canonical")
        return pack

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ContextPack) and self.to_bytes() == other.to_bytes()

    def __hash__(self) -> int:
        return hash(self.to_bytes())


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A prefix of a base pack plus the target suffix needed to rebuild it."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _require_digest(self.base_digest, "base_digest")
        _require_digest(self.target_digest, "target_digest")
        if isinstance(self.prefix_items, bool) or not isinstance(self.prefix_items, int) or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = tuple(self.appended)
        if any(not isinstance(item, bytes) for item in appended):
            raise ContextPackError("appended items must be bytes")
        object.__setattr__(self, "appended", appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta endpoints must be context packs")
        prefix = 0
        limit = min(len(base.items), len(target.items))
        while prefix < limit and base.items[prefix] == target.items[prefix]:
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical(
            {
                "schema": DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": [_b64encode(item) for item in self.appended],
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _require_exact_fields(_load_json(data), _DELTA_FIELDS, "context pack delta")
        if payload["schema"] != DELTA_SCHEMA:
            raise ContextPackError("unsupported context pack delta schema")
        raw_appended = payload["appended"]
        if not isinstance(raw_appended, list):
            raise ContextPackError("appended items must be a list")
        return cls(
            base_digest=_require_digest(payload["base_digest"], "base_digest"),
            target_digest=_require_digest(payload["target_digest"], "target_digest"),
            prefix_items=_require_int(payload["prefix_items"], "prefix_items"),
            appended=tuple(_b64decode(item) for item in raw_appended),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from a base pack and one delta."""

    if not isinstance(base, ContextPack):
        raise ContextPackError("base must be a context pack")
    if not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta must be a context pack delta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the supplied base pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("prefix_items exceeds the base pack item count")
    target = ContextPack((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("rebuilt pack does not match the delta target digest")
    return target


__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
