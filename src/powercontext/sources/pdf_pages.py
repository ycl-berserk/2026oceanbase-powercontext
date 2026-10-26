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

"""Page-level PDF Sources and exact evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

PDF_PAGE_SOURCE_NAME = "pdf-page"


class PDFDocumentInput(BaseModel):
    """One complete original PDF and its caller-stable document identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page extracted from a complete PDF document."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured PDF page addressed by document revision and physical page."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    identity = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(f"{document_id}\x00{document_sha256}\x00{page_number}".encode()).hexdigest()
        identity = f"pdf:sha256:{digest}:{page_number}"
    return identity


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of an original PDF in order."""

    if not isinstance(value.document_id, str) or not value.document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    content = value.content
    if not isinstance(content, bytes) or not content:
        raise ValueError("PDF content must be non-empty bytes")  # noqa: TRY003
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            if not reader.decrypt(""):
                raise ValueError("PDF requires a non-empty password")  # noqa: TRY003
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=hashlib.sha256(content).hexdigest(),
                page_number=page_number,
                text=page.extract_text() or "",
            )
            for page_number, page in enumerate(reader.pages, start=1)
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF document could not be parsed completely") from error
    return pages


class PDFPageAdapter:
    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        return PDFPageSource(
            name=pdf_page_source_id(value.document_id, value.document_sha256, value.page_number),
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_ADAPTER = PDFPageAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_ADAPTER,
    projections=(PDFPageTextEvidenceProjection(),),
)


_TOKEN_PATTERN = re.compile(r"[a-z]+|\d+")
_INDEX_LINE_PATTERN = re.compile(r"\s\d{1,3}$")
_ITEM_PREFIX_PATTERN = re.compile(r"^item\s+\d+[a-z]?\.\s*")
_NOTE_PREFIX_PATTERN = re.compile(r"^note\s+\d+[a-z]?\s*[—\-:.]?\s*")

_STOPWORD_WORDS = frozenset(
    "a an and are as at be been being but by can could did do does for from had has have how if in "
    "into is it its may might must no nor not of on only or other our out over own same should so "
    "some such than that the their them then there these they this those through to too under until "
    "up very was we were what when where which while who why will with would you your fy usd "
    "response respond perspective analyst details shown give given p l s t d ll re ve m "
    "statement financial consolidated note company inc subsidiary fiscal year table contents "
    "investment use us within answer question assume define detail report".split()
).union({"million", "millions", "billion", "billions"})

_EXPANSIONS: tuple[tuple[frozenset[str], tuple[str, ...], float], ...] = (
    (frozenset({"geography", "geographic", "region", "country", "worldwide", "global", "international"}),
     ("united", "states", "canada", "mexico", "latin", "america", "europe", "africa", "middle",
      "east", "south", "asia", "pacific", "australia", "zealand", "china", "japan", "india",
      "brazil", "kingdom", "segment", "division", "market"), 0.35),
    (frozenset({"legal", "litigation", "lawsuit", "battle", "proceeding", "claim", "settlement",
                "contingency", "regulatory"}),
     ("legal", "proceedings", "litigation", "claims", "settlements", "regulatory", "contingencies",
      "matters", "inquiry", "investigation", "court", "dispute"), 0.45),
    (frozenset({"ebitda"}),
     ("operating", "profit", "income", "depreciation", "amortization", "cash", "flows", "margin"), 0.4),
    (frozenset({"capex", "capital", "expenditure", "spending"}),
     ("capital", "spending", "expenditures", "purchases", "property", "plant", "equipment"), 0.4),
    (frozenset({"restructuring"}),
     ("restructuring", "impairment", "charges", "productivity", "plan", "severance", "costs"), 0.45),
    (frozenset({"depreciation", "amortization"}), ("depreciation", "amortization"), 0.35),
    (frozenset({"revenue", "sales"}), ("revenue", "net", "sales", "income", "growth"), 0.25),
    (frozenset({"margin"}), ("gross", "operating", "profit", "revenue", "income"), 0.35),
    (frozenset({"tax"}),
     ("income", "taxes", "provision", "effective", "rate", "deferred"), 0.3),
    (frozenset({"liquidity", "quick", "ratio", "working"}),
     ("cash", "equivalents", "current", "assets", "liabilities", "receivables", "inventories",
      "payables", "working", "capital"), 0.35),
    (frozenset({"dividend"}), ("dividends", "shares", "common", "stock", "payout"), 0.3),
    (frozenset({"debt", "borrowing", "lease", "obligation"}),
     ("debt", "borrowings", "leases", "obligations", "long", "term", "notes", "interest", "payable"), 0.3),
    (frozenset({"repurchase", "buyback"}), ("repurchase", "shares", "common", "stock"), 0.3),
    (frozenset({"inventory"}), ("inventories", "inventory", "cost", "sales"), 0.25),
    (frozenset({"customer"}), ("customers", "clients", "distributors", "retailers", "consumers"), 0.3),
    (frozenset({"product", "service", "offering"}),
     ("products", "services", "offerings", "brands", "categories"), 0.25),
    (frozenset({"employee", "headcount"}), ("employees", "headcount"), 0.25),
    (frozenset({"retain", "retention", "renew", "churn"}),
     ("retain", "retention", "renewal", "card", "members", "customers", "loyalty"), 0.3),
    (frozenset({"cyclical", "cyclicality"}),
     ("cyclical", "cycles", "economic", "demand", "downturn"), 0.3),
    (frozenset({"forecast", "outlook", "expect", "anticipate", "guidance"}),
     ("forecast", "outlook", "expect", "anticipate", "guidance", "projections", "future"), 0.2),
    (frozenset({"production", "capacity"}),
     ("production", "rate", "capacity", "increase", "decrease", "plant", "manufacturing"), 0.25),
    (frozenset({"segment", "division"}),
     ("segments", "division", "reportable", "sales", "revenue"), 0.3),
    (frozenset({"concentration", "concentrated"}),
     ("concentration", "customers", "suppliers", "revenue", "percent"), 0.3),
    (frozenset({"security", "registered", "exchange", "exhibit"}),
     ("securities", "registered", "exchange", "exhibit", "description", "capital", "stock"), 0.2),
    (frozenset({"drive", "drove", "driven", "change", "increase", "decrease", "growth", "decline"}),
     ("driven", "primary", "growth", "organic", "volume", "price", "mix", "foreign", "exchange"), 0.25),
)

_HEADERS: tuple[tuple[frozenset[str], tuple[str, ...], float], ...] = (
    (frozenset({"legal", "litigation", "lawsuit", "battle", "proceeding", "claim", "contingency"}),
     ("legal proceedings",), 8.0),
    (frozenset({"restructuring"}), ("restructuring",), 4.0),
    (frozenset({"income", "statement", "operation", "earning", "profit", "loss", "revenue", "sales",
                "margin", "ebitda", "tax", "depreciation", "amortization", "cost", "expense", "gross"}),
     ("statement of income", "statements of income", "statement of operations",
      "statements of operations", "statement of earnings"), 10.0),
    (frozenset({"cash", "flow", "capex", "capital", "expenditure", "depreciation", "amortization",
                "ebitda", "operating", "investing", "financing", "liquidity"}),
     ("statement of cash flows", "statements of cash flows"), 10.0),
    (frozenset({"balance", "sheet", "asset", "liability", "liquidity", "debt", "inventory",
                "receivable", "payable", "cash", "equity"}),
     ("balance sheet", "balance sheets"), 8.0),
    (frozenset({"property", "plant", "facility", "geography", "operate", "operation", "segment",
                "distribution", "manufacturing"}),
     ("item 2. properties", "item 2. property"), 3.0),
    (frozenset({"product", "service", "customer", "business", "segment", "geography", "operate",
                "operation", "brand", "competition", "employee"}),
     ("item 1. business",), 3.0),
    (frozenset({"segment", "division"}),
     ("segment information", "reportable segment", "reportable segments"), 3.0),
    (frozenset({"tax"}), ("income taxes",), 2.5),
    (frozenset({"revenue", "sales", "margin", "drive", "change", "growth", "liquidity", "capital",
                "restructuring", "cost", "expense", "operating", "profit"}),
     ("management's discussion and analysis",), 3.0),
    (frozenset({"risk", "litigation", "legal", "cybersecurity", "inflation", "cyber"}),
     ("risk factors",), 2.0),
    (frozenset({"estimate", "impairment", "goodwill", "intangible", "tax"}),
     ("critical accounting estimates", "critical accounting policies"), 2.0),
    (frozenset({"interest", "rate", "currency", "foreign", "exchange", "commodity", "risk"}),
     ("quantitative and qualitative disclosures about market risk",), 2.0),
)


_BIGRAM_SYNONYMS: tuple[tuple[tuple[str, str], tuple[str, str], float], ...] = (
    (("operat", "incom"), ("operat", "profit"), 2.0),
    (("net", "revenu"), ("net", "sale"), 1.0),
)


def _stem(term: str) -> str:
    if len(term) <= 3 or term.isdigit():
        return term
    if term.endswith("ies") and len(term) > 4:
        term = term[:-3] + "y"
    elif term.endswith(("sses", "shes", "ches", "xes")):
        term = term[:-2]
    elif term.endswith("s") and not term.endswith(("ss", "us", "is")):
        term = term[:-1]
    if term.endswith("ing") and len(term) > 5:
        term = term[:-3]
    elif term.endswith("ed") and len(term) > 4:
        term = term[:-2]
    if term.endswith("e") and len(term) > 4:
        term = term[:-1]
    return term


_STOPWORDS = frozenset(_stem(word) for word in _STOPWORD_WORDS)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        term
        for raw in _TOKEN_PATTERN.findall(text.lower())
        if (term := _stem(raw)) not in _STOPWORDS
    )


def _stems(text: str) -> tuple[str, ...]:
    return tuple(_stem(raw) for raw in _TOKEN_PATTERN.findall(text.lower()))


_STEM_EXPANSIONS = tuple(
    (frozenset(_stem(trigger) for trigger in triggers), tuple(_stem(term) for term in terms), weight)
    for triggers, terms, weight in _EXPANSIONS
)
_STEM_HEADERS = tuple(
    (frozenset(_stem(trigger) for trigger in triggers), phrases, bonus)
    for triggers, phrases, bonus in _HEADERS
)


def _query_weights(question: str) -> tuple[dict[str, float], frozenset[tuple[str, str]], frozenset[str]]:
    stems = _stems(question)
    weights = {term: float(min(count, 3)) for term, count in Counter(stems).items() if term not in _STOPWORDS}
    present = set(stems)
    for triggers, terms, weight in _STEM_EXPANSIONS:
        if present & triggers:
            for term in terms:
                weights[term] = max(weights.get(term, 0.0), weight)
    content = [term for term in stems if term not in _STOPWORDS]
    bigrams = frozenset(
        pair for pair in zip(content, content[1:]) if pair[0] != pair[1]
    )
    return weights, bigrams, frozenset(present)


def _header_lines(text: str) -> tuple[str, ...]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.lower().split())
        if not line:
            continue
        lines.append(line)
        variant = line[13:] if line.startswith("consolidated ") else line
        if variant != line:
            lines.append(variant)
        stripped = _NOTE_PREFIX_PATTERN.sub("", _ITEM_PREFIX_PATTERN.sub("", variant))
        if stripped != line and stripped != variant:
            lines.append(stripped)
    return tuple(lines)


def _looks_like_index(text: str) -> bool:
    entries = 0
    for line in text.splitlines():
        stripped = line.strip()
        match = _INDEX_LINE_PATTERN.search(stripped)
        if match is None or len(stripped) < 4:
            continue
        body = stripped[: match.start()]
        if "$" in body or "%" in body or "," in body:
            continue
        if any(character.isdigit() for character in body) and not re.match(
            r"(?i)^item\s+\d+[a-z]?\.", body
        ):
            continue
        entries += 1
    return entries >= 5


@dataclass(frozen=True, slots=True)
class _PageRecord:
    citation: MemoryCitation
    entry_version_id: str
    tokens: tuple[str, ...]
    location: tuple[str, int]
    header_lines: tuple[str, ...]
    is_index: bool


def _page_location(source_id: str) -> tuple[str, int] | None:
    if not isinstance(source_id, str) or not source_id.startswith("pdf:"):
        return None
    prefix, _, raw_page = source_id.rpartition(":")
    if not prefix or not raw_page.isdigit():
        return None
    return (prefix, int(raw_page))


def _page_record(record: Any) -> _PageRecord | None:
    entry = record.entry
    location = None
    for reference in entry.sources:
        location = _page_location(reference.source_id)
        if location is not None:
            break
    if location is None:
        return None
    text = entry.text
    return _PageRecord(
        citation=record.citation,
        entry_version_id=entry.entry_version_id,
        tokens=_tokens(text),
        location=location,
        header_lines=_header_lines(text),
        is_index=_looks_like_index(text),
    )


def _score(
    records: list[_PageRecord],
    question: str,
) -> list[tuple[float, _PageRecord]]:
    weights, query_bigrams, present = _query_weights(question)
    document_count = len(records)
    average_length = sum(len(record.tokens) for record in records) / document_count
    document_frequency: Counter[str] = Counter()
    for record in records:
        document_frequency.update(set(record.tokens))
    idf = {
        term: math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))
        for term, frequency in document_frequency.items()
    }
    for term in weights:
        idf.setdefault(term, 0.0)
    k1, b = 1.2, 0.65
    scored: list[tuple[float, _PageRecord]] = []
    for record in records:
        frequencies = Counter(record.tokens)
        length = len(record.tokens)
        score = 0.0
        for term, weight in weights.items():
            frequency = frequencies.get(term, 0)
            if frequency:
                score += (
                    weight
                    * idf[term]
                    * frequency
                    * (k1 + 1.0)
                    / (frequency + k1 * (1.0 - b + b * length / average_length))
                )
        page_bigrams = set(zip(record.tokens, record.tokens[1:]))
        score += 0.6 * len(query_bigrams & page_bigrams)
        for query_synonym, page_synonym, synonym_bonus in _BIGRAM_SYNONYMS:
            if query_synonym in query_bigrams and page_synonym in page_bigrams:
                score += synonym_bonus
        if record.is_index:
            score -= 5.0
        else:
            bonus = 0.0
            for triggers, phrases, header_bonus in _STEM_HEADERS:
                if present & triggers and any(
                    line.startswith(phrase) for phrase in phrases for line in record.header_lines
                ):
                    bonus = max(bonus, header_bonus)
            score += bonus
        scored.append((score, record))
    return scored


async def _listed_records(memory: Any) -> list[_PageRecord]:
    lister = getattr(memory, "list", None)
    if not callable(lister):
        return []
    page = await lister()
    records = (_page_record(record) for record in page.entries)
    return [record for record in records if record is not None]


async def _search_records(memory: Any, question: str, limit: int) -> list[_PageRecord]:
    page = await memory.search(
        SearchMemoryRequest(query=question, mode="auto", limit=max(limit, 40))
    )
    records: list[_PageRecord] = []
    for hit in page.hits:
        citation = MemoryCitation(
            memory_ref=hit.memory_ref,
            entry_id=hit.entry_id,
            entry_version_id=hit.entry_version_id,
        )
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        page_record = _page_record(record)
        if page_record is not None:
            records.append(page_record)
    return records


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return distinct exact citations for the evidence pages most likely to answer a question."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")  # noqa: TRY003
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    records = await _listed_records(memory)
    if not records:
        try:
            records = await _search_records(memory, question, limit)
        except Exception:
            return ()
    if not records:
        return ()
    ranked = sorted(_score(records, question), key=lambda item: (-item[0], item[1].location))
    selected: list[MemoryCitation] = []
    seen: set[tuple[str, int]] = set()
    for _, record in ranked:
        if record.location in seen:
            continue
        seen.add(record.location)
        selected.append(record.citation)
        if len(selected) >= limit:
            break
    return tuple(selected)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
