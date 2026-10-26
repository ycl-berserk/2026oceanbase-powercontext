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

"""Cross-call embedding request coalescing with a bounded successful-vector cache."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True, slots=True)
class _BatchValue:
    vector: EmbeddingVector
    batch_id: int
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Share in-flight text embeddings across callers and reuse successful vectors."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if isinstance(max_batch_size, bool) or not isinstance(max_batch_size, int) or max_batch_size <= 0:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, (int, float)) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        self._model = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_ms = float(coalesce_ms)
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._pending: deque[str] = deque()
        self._requests: dict[str, asyncio.Future[_BatchValue]] = {}
        self._wakeup = asyncio.Event()
        self._lock = asyncio.Lock()
        self._dispatcher: asyncio.Task[None] | None = None
        self._batch_counter = 0

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        if not isinstance(texts, tuple) or any(not isinstance(text, str) for text in texts):
            raise ValueError("texts must be a tuple of strings")  # noqa: TRY003
        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        unique = tuple(dict.fromkeys(texts))
        cache_values: dict[str, EmbeddingVector] = {}
        waiters: dict[str, asyncio.Future[_BatchValue]] = {}
        created = False

        async with self._lock:
            for text in unique:
                cached = self._lookup(text)
                if cached is not None:
                    cache_values[text] = cached
                    continue
                future = self._requests.get(text)
                if future is None:
                    future = asyncio.get_running_loop().create_future()
                    self._requests[text] = future
                    self._pending.append(text)
                    created = True
                waiters[text] = future
            if created:
                self._ensure_dispatcher()
                self._wakeup.set()

        if waiters:
            resolved = await asyncio.gather(*(asyncio.shield(future) for future in waiters.values()))
            for text, value in zip(waiters, resolved, strict=True):
                cache_values[text] = value.vector
            usages = self._usage_for(resolved)
        else:
            usages = InferenceUsage(requests=0, input_tokens=0, output_tokens=0)

        return EmbeddingResult(
            vectors=tuple(cache_values[text] for text in texts),
            usage=usages,
        )

    def _lookup(self, text: str) -> EmbeddingVector | None:
        if self._cache_size == 0:
            return None
        vector = self._cache.get(text)
        if vector is not None:
            self._cache.move_to_end(text)
        return vector

    def _store(self, text: str, vector: EmbeddingVector) -> None:
        if self._cache_size == 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    @staticmethod
    def _usage_for(values) -> InferenceUsage:
        batch_usage: dict[int, InferenceUsage] = {}
        for value in values:
            batch_usage.setdefault(value.batch_id, value.usage)
        requests = 0
        input_tokens: int | None = None
        output_tokens: int | None = None
        for usage in batch_usage.values():
            requests += usage.requests
            if usage.input_tokens is not None:
                input_tokens = (input_tokens or 0) + usage.input_tokens
            if usage.output_tokens is not None:
                output_tokens = (output_tokens or 0) + usage.output_tokens
        if not batch_usage:
            return InferenceUsage(requests=0, input_tokens=0, output_tokens=0)
        return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)

    def _ensure_dispatcher(self) -> None:
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.get_running_loop().create_task(self._dispatch())

    async def _dispatch(self) -> None:
        while True:
            async with self._lock:
                if not self._pending:
                    self._wakeup.clear()
                    has_pending = False
                else:
                    has_pending = True
            if not has_pending:
                await self._wakeup.wait()
                continue

            if self._coalesce_ms > 0:
                await asyncio.sleep(self._coalesce_ms / 1000.0)
            else:
                await asyncio.sleep(0)

            async with self._lock:
                batch: list[str] = []
                while self._pending and len(batch) < self._max_batch_size:
                    text = self._pending.popleft()
                    future = self._requests.get(text)
                    if future is None or future.done():
                        continue
                    batch.append(text)
            if batch:
                asyncio.get_running_loop().create_task(self._run_batch(batch))

    async def _run_batch(self, texts: list[str]) -> None:
        self._batch_counter += 1
        batch_id = self._batch_counter
        try:
            result = await self._model.embed(tuple(texts))
        except BaseException as error:
            await self._finish_failure(texts, error)
            return
        if len(result.vectors) != len(texts):
            await self._finish_failure(
                texts,
                ValueError(
                    f"embedding provider returned {len(result.vectors)} vectors for {len(texts)} texts"
                ),
            )
            return
        await self._finish_success(texts, tuple(result.vectors), batch_id, result.usage)

    async def _finish_success(
        self,
        texts: list[str],
        vectors: tuple[EmbeddingVector, ...],
        batch_id: int,
        usage: InferenceUsage,
    ) -> None:
        async with self._lock:
            for text, vector in zip(texts, vectors, strict=True):
                self._store(text, vector)
                future = self._requests.pop(text, None)
                if future is not None and not future.done():
                    future.set_result(_BatchValue(vector=vector, batch_id=batch_id, usage=usage))

    async def _finish_failure(self, texts: list[str], error: BaseException) -> None:
        async with self._lock:
            for text in texts:
                future = self._requests.pop(text, None)
                if future is not None and not future.done():
                    future.set_exception(error)


__all__ = ["CoalescingEmbeddingModel"]
