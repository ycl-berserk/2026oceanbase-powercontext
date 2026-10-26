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

"""HTTP cross-encoder reranking with global cross-batch selection."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score Memory candidates from an HTTP service in bounded batches."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty string")  # noqa: TRY003
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        if not isinstance(candidates, tuple) or not candidates:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            batch_ranks = tuple(range(start + 1, start + len(batch) + 1))
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text}
                    for rank, candidate in zip(batch_ranks, batch, strict=True)
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            requests += 1
            if not response.is_success:
                response.raise_for_status()
            scores.update(self._parse_scores(response, batch_ranks))

        selected = sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        return MemoryRerankDecision(selected_ranks=tuple(selected), usage=InferenceUsage(requests=requests))

    @staticmethod
    def _parse_scores(response: httpx.Response, batch_ranks: tuple[int, ...]) -> dict[int, float]:
        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError("rerank response is not valid JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"scores"}:
            raise ValueError("rerank response must contain exactly one scores field")  # noqa: TRY003
        raw_scores = payload["scores"]
        if not isinstance(raw_scores, list):
            raise ValueError("rerank scores must be a list")  # noqa: TRY003

        expected = set(batch_ranks)
        parsed: dict[int, float] = {}
        for item in raw_scores:
            if not isinstance(item, dict) or set(item) != {"rank", "score"}:
                raise ValueError("each rerank score must contain exactly rank and score")  # noqa: TRY003
            rank = item["rank"]
            score = item["score"]
            if isinstance(rank, bool) or not isinstance(rank, int) or rank not in expected:
                raise ValueError("rerank score rank is outside its batch")  # noqa: TRY003
            if rank in parsed:
                raise ValueError("rerank response repeated a rank")  # noqa: TRY003
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError("rerank score must be numeric")  # noqa: TRY003
            numeric = float(score)
            if not math.isfinite(numeric):
                raise ValueError("rerank score must be finite")  # noqa: TRY003
            parsed[rank] = numeric
        if set(parsed) != expected:
            raise ValueError("rerank response did not cover every batch rank once")  # noqa: TRY003
        return parsed


__all__ = ["HTTPMemoryReranker"]
