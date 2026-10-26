from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .memory import MemoryHit
from .store import Evidence

EXTRACTIVE_NOTE = "当前为本地摘录模式：未调用大模型，以上要点直接来自你的笔记。"


@dataclass
class GeneratedText:
    text: str
    mode: str
    model: str | None = None
    warning: str | None = None
    used_chunk_ids: list[str] = field(default_factory=list)


def _shorten(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，、；;：: ") + "…"


def _first_sentence(text: str, limit: int = 110) -> str:
    match = re.search(r"[^。！？!?；;]+[。！？!?；;]?", text)
    sentence = match.group(0).strip() if match else text
    return _shorten(sentence, limit)


def select_answer_evidence(evidence: list[Evidence], limit: int = 4) -> list[Evidence]:
    """只取相关度连续靠前的片段：融合分过低时立即截断，避免用无关内容凑数。"""
    selected: list[Evidence] = []
    for index, item in enumerate(evidence):
        if index > 0 and item.fts_rank is None and item.score < 0.6:
            break
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


class AnswerWriter:
    """优先调用 DeepSeek；没有密钥或调用失败时使用可核对的本地摘录。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return self.settings.llm_mode == "deepseek"

    def answer(
        self,
        question: str,
        evidence: list[Evidence],
        memories: list[MemoryHit],
        course: str | None,
    ) -> GeneratedText:
        if not evidence:
            text = (
                "知识库里还没有与这个问题相关的段落。"
                "可以先导入课程笔记，或换一个更具体的问法，例如包含章节名或关键术语。"
            )
            return GeneratedText(text=text, mode="no-evidence")

        evidence = select_answer_evidence(evidence)
        used_chunk_ids = [item.chunk_id for item in evidence]

        if self.available:
            try:
                return self._call_llm(
                    system=(
                        "你是「温故 ReviewMate」，一名严谨的课程复习助教。"
                        "只能依据用户提供的笔记片段回答，不得编造。"
                        "每个结论后用 [编号] 标注来源；编号必须来自给出的片段。"
                        "用中文回答，先给结论，再用 2-4 个要点展开，最后给一个自测问题。"
                        "控制在 400 字以内。"
                    ),
                    user=self._answer_prompt(question, evidence, memories, course),
                    mode="deepseek",
                    used_chunk_ids=used_chunk_ids,
                )
            except Exception as exc:  # noqa: BLE001 - 任何模型故障都降级
                fallback = self._extractive_answer(question, evidence, memories, course)
                fallback.mode = "extractive-fallback"
                fallback.warning = f"大模型调用失败，已降级为本地摘录：{exc.__class__.__name__}"
                return fallback

        return self._extractive_answer(question, evidence, memories, course)

    def plan(
        self,
        *,
        course: str | None,
        weak_points: list[MemoryHit],
        documents: list[dict[str, Any]],
    ) -> GeneratedText:
        if self.available and (weak_points or documents):
            try:
                return self._call_llm(
                    system=(
                        "你是「温故 ReviewMate」的复习规划助手。"
                        "根据用户的薄弱点与笔记目录，制定一份可在 30-45 分钟内完成的复习计划。"
                        "计划要具体到章节和动作（回顾、对照、自测），使用中文编号列表，控制在 350 字以内。"
                        "不要编造资料中没有的章节。"
                    ),
                    user=self._plan_prompt(course, weak_points, documents),
                    mode="deepseek",
                )
            except Exception as exc:  # noqa: BLE001
                fallback = self._template_plan(course, weak_points, documents)
                fallback.mode = "template-fallback"
                fallback.warning = f"大模型调用失败，已使用本地计划模板：{exc.__class__.__name__}"
                return fallback
        return self._template_plan(course, weak_points, documents)

    # ---------- prompts ----------

    def _answer_prompt(
        self,
        question: str,
        evidence: list[Evidence],
        memories: list[MemoryHit],
        course: str | None,
    ) -> str:
        lines = [f"课程范围：{course or '全部课程'}", f"问题：{question}", "", "笔记片段："]
        for index, item in enumerate(evidence, start=1):
            page = f"第 {item.page_no} 页，" if item.page_no else ""
            lines.append(
                f"[{index}] 《{item.title}》· {item.heading}（{page}{item.course}）\n{item.content}"
            )
        if memories:
            lines.extend(["", "用户此前标记过的学习记忆："])
            for memory in memories[:5]:
                lines.append(f"- {memory.text}")
        return "\n".join(lines)

    def _plan_prompt(
        self,
        course: str | None,
        weak_points: list[MemoryHit],
        documents: list[dict[str, Any]],
    ) -> str:
        lines = [f"复习范围：{course or '全部课程'}", "", "薄弱点："]
        if weak_points:
            lines.extend(f"- {item.text}" for item in weak_points[:8])
        else:
            lines.append("- 尚未记录薄弱点")
        lines.extend(["", "可用笔记："])
        for document in documents[:12]:
            lines.append(f"- 《{document['title']}》（{document['course']}，{document['chunk_count']} 段）")
        return "\n".join(lines)

    # ---------- local fallbacks ----------

    def _extractive_answer(
        self,
        question: str,
        evidence: list[Evidence],
        memories: list[MemoryHit],
        course: str | None,
    ) -> GeneratedText:
        lines = ["笔记里最相关的段落是：", ""]
        for index, item in enumerate(evidence[:4], start=1):
            page = f"第 {item.page_no} 页 · " if item.page_no else ""
            lines.append(
                f"{index}. **{item.heading}**（《{item.title}》，{page}{item.course}）"
                f"：{_first_sentence(item.content)} [{index}]"
            )
        if memories:
            lines.extend(
                [
                    "",
                    "结合你之前标记的薄弱点：",
                    *[f"- {_shorten(memory.text, 90)}" for memory in memories[:3]],
                ]
            )
        lines.extend(["", EXTRACTIVE_NOTE])
        return GeneratedText(
            text="\n".join(lines),
            mode="extractive",
            used_chunk_ids=[item.chunk_id for item in evidence[:4]],
        )

    def _template_plan(
        self,
        course: str | None,
        weak_points: list[MemoryHit],
        documents: list[dict[str, Any]],
    ) -> GeneratedText:
        scope = course or "全部课程"
        lines = [f"复习计划 · {scope}（约 35 分钟）", ""]
        if weak_points:
            lines.append("1. 先处理薄弱点（10 分钟）")
            for memory in weak_points[:3]:
                lines.append(f"   - 回看并复述：{_shorten(memory.text, 80)}")
            step = 2
        else:
            lines.append("1. 先用 5 分钟在「学习记忆」里记录一个最没把握的知识点。")
            step = 2
        if documents:
            lines.append(f"{step}. 精读并做对照笔记（20 分钟）")
            for document in documents[:3]:
                lines.append(
                    f"   - 《{document['title']}》（{document['course']}，共 {document['chunk_count']} 段）"
                )
            step += 1
        lines.extend(
            [
                f"{step}. 自测与回收（5 分钟）",
                "   - 针对上面的每个知识点，用自己的话回答一次，再回到原文核对。",
                "   - 仍不清楚的内容，标记为新的薄弱点，下一次复习会优先出现。",
                "",
                "本地计划模板生成（未配置大模型）。",
            ]
        )
        return GeneratedText(text="\n".join(lines), mode="template")

    def _call_llm(
        self,
        *,
        system: str,
        user: str,
        mode: str,
        used_chunk_ids: list[str] | None = None,
    ) -> GeneratedText:
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 900,
            "stream": False,
        }
        response = httpx.post(
            f"{self.settings.deepseek_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()
        return GeneratedText(
            text=text,
            mode=mode,
            model=self.settings.deepseek_model,
            used_chunk_ids=used_chunk_ids or [],
        )
