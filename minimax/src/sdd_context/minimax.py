"""MiniMax 调用：仅在开发期生成一次代码修改，并保留可核对记录。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "Minimax-M3"

SYSTEM_PROMPT = """你是谨慎的软件工程师。根据给定的任务、规格、代码和测试，输出最小必要的代码修改。
要求：
1. 只修改任务涉及的代码，不要改动测试；
2. 修改必须满足规格条目，并保持既有行为；
3. 输出一个 unified diff（```diff 代码块），不要输出其他解释；
4. diff 必须能直接应用到给定的文件路径。"""

DIFF_BLOCK = re.compile(r"```(?:diff|patch)\s*\n(.*?)```", re.S)


@dataclass
class MiniMaxReply:
    model: str
    content: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class MiniMaxClient:
    """同时支持 OpenAI 与 Anthropic 两种消息格式。

    - 官方 MiniMax / OpenCode Go 的 M3.1 Flash：``api_style="openai"``
    - OpenCode Go 的 MiniMax M3：``api_style="anthropic"``
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        api_style: str = "openai",
        timeout: float = 180.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_style = api_style
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    @classmethod
    def from_env(cls) -> MiniMaxClient:
        api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少 MINIMAX_API_KEY")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL),
            api_style=os.environ.get("MINIMAX_API_STYLE", "openai").strip().lower(),
        )

    def chat(self, prompt: str, temperature: float = 0.2, max_tokens: int = 4096) -> MiniMaxReply:
        if self.api_style == "anthropic":
            return self._chat_anthropic(prompt, temperature, max_tokens)
        return self._chat_openai(prompt, temperature, max_tokens)

    def _chat_openai(self, prompt: str, temperature: float, max_tokens: int) -> MiniMaxReply:
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return MiniMaxReply(
            model=payload.get("model", self.model),
            content=content,
            usage=payload.get("usage", {}),
            raw=payload,
        )

    def _chat_anthropic(self, prompt: str, temperature: float, max_tokens: int) -> MiniMaxReply:
        response = self._client.post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        )
        return MiniMaxReply(
            model=payload.get("model", self.model),
            content=content,
            usage=payload.get("usage", {}),
            raw=payload,
        )

    def close(self) -> None:
        self._client.close()


def build_prompt(task: str, context: dict[str, Any]) -> str:
    return (
        f"任务：{task}\n\n"
        "以下是检索得到的任务上下文（规格、代码、测试）：\n"
        f"{context}\n\n"
        "请只针对任务涉及的代码给出 unified diff。"
    )


def extract_diff(content: str) -> str | None:
    match = DIFF_BLOCK.search(content)
    if match:
        return match.group(1).strip() + "\n"
    return None
