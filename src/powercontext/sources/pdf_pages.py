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
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a non-empty password")  # noqa: TRY003, TRY301
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
        raise ValueError("PDF document could not be parsed completely") from error  # noqa: TRY003
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

_PREPROCESS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[-–—/]"), " "),  # noqa: RUF001 - en/em dashes separate financial terms
    (re.compile(r"\bm\s*&\s*a\b", re.I), "mergers acquisitions"),
    (re.compile(r"\br\s*&\s*d\b", re.I), "research development"),
    (re.compile(r"\bs\s*g\s*&\s*a\b", re.I), "selling general administrative"),
    (re.compile(r"\bcogs\b", re.I), "cost goods sold"),
    (re.compile(r"\bd\s*&\s*a\b", re.I), "depreciation amortization"),
    (re.compile(r"\bpp\s*&\s*e\b", re.I), "property plant equipment"),
    (re.compile(r"\bppne\b", re.I), "property plant equipment net"),
    (re.compile(r"\bppe\b", re.I), "property plant equipment"),
    (re.compile(r"\byoy\b", re.I), "year over year"),
    (re.compile(r"\bu\.\s*s\.\s*a?\.?", re.I), "united states "),
    (re.compile(r"\bfy\s*'?(\d{2})\b", re.I), r"20\1"),
    (re.compile(r"\bfy\s*(\d{4})\b", re.I), r"\1"),
)

_STOPWORDS_WORDS = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "might",
    "must",
    "no",
    "nor",
    "not",
    "of",
    "on",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "same",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "fy",
    "usd",
    "response",
    "respond",
    "perspective",
    "analyst",
    "details",
    "shown",
    "give",
    "given",
    "p",
    "l",
    "s",
    "t",
    "d",
    "ll",
    "re",
    "ve",
    "m",
    "investment",
    "use",
    "us",
    "within",
    "answer",
    "question",
    "assume",
    "define",
    "detail",
    "report",
    "based",
    "data",
    "primary",
    "major",
    "main",
    "overall",
    "historically",
    "consistent",
    "roughly",
    "relevant",
    "metric",
    "useful",
    "like",
    "please",
    "state",
    "explain",
    "calculate",
    "conventional",
    "meaningful",
    "many",
    "much",
    "times",
    "approximately",
    "able",
    "between",
    "period",
    "represent",
    "exclude",
    "excluding",
    "impact",
    "any",
    "more",
    "less",
    "percentage",
    "percent",
    "ratio",
    "statement",
    "financial",
    "consolidated",
    "note",
    "company",
    "inc",
    "subsidiary",
    "fiscal",
    "year",
    "table",
    "contents",
    "business",
    "value",
    "amount",
    "one",
    "two",
    "three",
    "first",
    "second",
    "third",
    "whether",
    "either",
    "neither",
    "both",
    "each",
    "every",
    "all",
    "others",
    "same",
    "different",
    "various",
    "following",
    "respectively",
    "about",
    "required",
    "requirements",
    "include",
    "includes",
    "including",
    "without",
    "during",
    "against",
    "upon",
    "also",
    "may",
    "million",
    "millions",
    "billion",
    "billions",
])

_CANONICAL: dict[str, str] = {
    "acquisition": "acquisition",
    "acquisitions": "acquisition",
    "acquire": "acquisition",
    "acquired": "acquisition",
    "acquires": "acquisition",
    "acquiring": "acquisition",
    "merger": "acquisition",
    "mergers": "acquisition",
    "retain": "retain",
    "retains": "retain",
    "retained": "retain",
    "retaining": "retain",
    "retention": "retain",
    "grow": "grow",
    "grows": "grow",
    "grew": "grow",
    "grown": "grow",
    "growing": "grow",
    "growth": "grow",
    "sale": "sale",
    "sales": "sale",
    "sell": "sale",
    "sells": "sale",
    "sold": "sale",
    "selling": "sale",
    "loss": "loss",
    "losses": "loss",
    "lose": "loss",
    "loses": "loss",
    "lost": "loss",
    "losing": "loss",
    "inventory": "inventory",
    "inventories": "inventory",
    "borrow": "borrow",
    "borrows": "borrow",
    "borrowing": "borrow",
    "borrowings": "borrow",
    "operate": "operate",
    "operates": "operate",
    "operated": "operate",
    "operating": "operate",
    "operation": "operate",
    "operations": "operate",
    "operational": "operate",
    "largest": "large",
    "larger": "large",
    "highest": "high",
    "higher": "high",
    "lowest": "low",
    "lower": "low",
    "consistency": "consist",
    "consistent": "consist",
    "fluctuate": "fluctuat",
    "fluctuates": "fluctuat",
    "fluctuating": "fluctuat",
    "fluctuation": "fluctuat",
    "fluctuations": "fluctuat",
    "competitive": "compet",
    "competition": "compet",
    "compete": "compet",
    "estimate": "estimat",
    "estimates": "estimat",
    "estimated": "estimat",
    "impair": "impair",
    "impaired": "impair",
    "impairment": "impair",
    "depreciate": "depreciation",
    "depreciated": "depreciation",
    "depreciation": "depreciation",
    "amortize": "amortization",
    "amortized": "amortization",
    "amortization": "amortization",
    "litigation": "litigation",
    "litigations": "litigation",
    "litigate": "litigation",
    "employee": "employee",
    "employees": "employee",
    "headcount": "employee",
    "repurchase": "repurchase",
    "repurchases": "repurchase",
    "buyback": "repurchase",
    "dividend": "dividend",
    "dividends": "dividend",
    "capex": "capital",
}
for _raw, _target in list(_CANONICAL.items()):
    for _token in _target.split():
        _CANONICAL.setdefault(_token, _token)

_INTENT_TERMS: dict[str, tuple[str, ...]] = {
    "capital": (
        "capital intensive",
        "capital expenditure",
        "capital expenditures",
        "capital spending",
        "capex",
        "property plant equipment",
        "ppne",
        "ppe",
        "purchases of property",
        "investment in property",
        "spending on property",
        "additions to property",
    ),
    "gross_margin": ("gross margin", "gross margins", "gross profit"),
    "operating_margin": ("operating margin", "operating income", "operating profit", "income from operations"),
    "ebitda": ("ebitda",),
    "revenue": ("revenue", "revenues", "net sales", "sales", "top line"),
    "net_income": ("net income", "net earnings", "net profit"),
    "tax": ("effective tax rate", "tax rate", "income tax", "income taxes", "provision for tax", "tax expense"),
    "inventory": ("inventory", "inventories", "inventory turnover"),
    "liquidity": ("quick ratio", "current ratio", "liquidity", "working capital"),
    "debt": (
        "debt",
        "debts",
        "borrowing",
        "borrowings",
        "leverage",
        "notes payable",
        "long-term debt",
        "long term debt",
    ),
    "acquisitions": (
        "acquisition",
        "acquisitions",
        "acquire",
        "acquired",
        "m&a",
        "merger",
        "mergers",
        "mergers acquisitions",
        "business combination",
        "business combinations",
    ),
    "legal": (
        "legal",
        "litigation",
        "lawsuit",
        "lawsuits",
        "legal battles",
        "proceedings",
        "claims",
        "contingency",
        "contingencies",
        "regulatory",
    ),
    "customers": (
        "customer",
        "customers",
        "client",
        "clients",
        "customer concentration",
        "primary customers",
        "card members",
        "card member",
    ),
    "geography": (
        "geography",
        "geographies",
        "geographic",
        "region",
        "regions",
        "country",
        "countries",
        "operates in",
        "operating in",
        "operations in",
    ),
    "products": ("product", "products", "service", "services", "offering", "offerings"),
    "segments": (
        "segment",
        "segments",
        "division",
        "divisions",
        "business unit",
        "reporting segment",
        "reportable segment",
    ),
    "capital_return": ("dividend", "dividends", "repurchase", "repurchases", "buyback", "share repurchase"),
    "restructuring": ("restructuring", "restructurings", "impairment", "impairments"),
    "ppe": ("property plant equipment", "ppne", "ppe", "property, plant and equipment"),
    "properties": ("properties", "property", "facilities", "plants"),
    "risk": ("risk", "risks", "risk factors"),
    "outlook": ("guidance", "outlook", "forecast", "forecasts", "expect", "expects", "anticipate"),
    "retention": ("retain", "retains", "retention", "retained", "churn"),
    "securities": ("securities", "registered", "exchange", "trading symbol", "exhibit"),
    "change": (
        "what drove",
        "driven",
        "driver",
        "drivers",
        "drove",
        "change",
        "changes",
        "increase",
        "increased",
        "decrease",
        "decreased",
        "decline",
        "declined",
        "grow",
        "growth",
    ),
}

_INTENT_BOOSTS: dict[str, dict[str, float]] = {
    "capital": {
        "income": 10,
        "cashflow": 10,
        "balance": 10,
        "ppne_note": 8,
        "analysis": 4,
        "business": 2,
        "segment": 6,
        "capital_spend": 8,
    },
    "gross_margin": {"income": 14, "analysis": 3, "summary": 3},
    "operating_margin": {"income": 14, "analysis": 3},
    "ebitda": {"income": 10, "cashflow": 10, "analysis": 2},
    "revenue": {"income": 8, "analysis": 3, "segment": 7},
    "net_income": {"income": 10, "analysis": 3},
    "income": {"income": 16, "analysis": 2},
    "balance": {"balance": 16, "analysis": 2},
    "cashflow": {"cashflow": 16},
    "tax": {"income": 6, "tax_note": 10, "summary": 5, "analysis": 2},
    "inventory": {"balance": 8, "income": 5},
    "liquidity": {"balance": 10, "income": 3, "cashflow": 4},
    "debt": {"balance": 6, "debt_note": 10},
    "acquisitions": {"acquisitions_note": 12},
    "legal": {"legal_note": 12, "risk": 2},
    "customers": {"business": 5, "risk": 5, "analysis": 3, "segment": 4},
    "geography": {"geography": 14, "segment": 8, "business": 4, "analysis": 2},
    "products": {"business": 8, "segment": 6, "income": 3},
    "segments": {"segment": 12, "analysis": 4},
    "capital_return": {"equity": 8, "cashflow": 6, "analysis": 3},
    "restructuring": {"income": 5, "restructuring_note": 8, "analysis": 3},
    "ppe": {"balance": 8, "ppne_note": 6},
    "properties": {"properties": 10},
    "risk": {"risk": 8},
    "outlook": {"analysis": 6, "risk": 3},
    "retention": {"business": 6, "analysis": 5, "mda": 5},
    "securities": {"cover": 8, "summary": 3},
    "change": {"analysis": 4, "mda": 4},
}

_INTENT_PHRASES: dict[str, tuple[tuple[tuple[str, ...], float], ...]] = {
    "gross_margin": (
        (("gross", "profit"), 4),
        (("gross", "margin"), 4),
        (("cost", "sale"), 3),
        (("cost", "product", "sale"), 3),
        (("net", "sale"), 1),
        (("revenue",), 0.5),
    ),
    "operating_margin": (
        (("operate", "income"), 4),
        (("operate", "profit"), 3),
        (("operate", "margin"), 3),
        (("income", "from", "operate"), 2),
    ),
    "ebitda": (
        (("operate", "income"), 3),
        (("depreciation",), 2),
        (("amortization",), 2),
        (("net", "income"), 1),
    ),
    "capital": (
        (("capital", "expenditure"), 5),
        (("property", "plant"), 4),
        (("plant", "equipment"), 3),
        (("purchase", "property"), 3),
        (("capital", "spending"), 4),
        (("capital", "intensive"), 3),
        (("depreciation",), 1),
    ),
    "inventory": (
        (("cost", "sale"), 4),
        (("cost", "product", "sale"), 4),
        (("inventory",), 3),
    ),
    "liquidity": (
        (("current", "asset"), 2),
        (("current", "liability"), 2),
        (("cash", "equivalent"), 2),
        (("inventory",), 1),
        (("receivable",), 1),
    ),
    "debt": (
        (("long", "term", "debt"), 4),
        (("debt", "outstanding"), 4),
        (("total", "debt"), 3),
        (("borrow",), 2),
        (("note", "payable"), 3),
        (("interest", "expense"), 1),
    ),
    "tax": (
        (("effective", "tax", "rate"), 4),
        (("provision", "income", "tax"), 4),
        (("income", "tax", "expense"), 3),
        (("deferred", "tax"), 2),
    ),
    "customers": (
        (("customer", "concentration"), 4),
        (("limited", "number"), 3),
        (("significant", "portion"), 3),
        (("united", "states", "government"), 3),
        (("commercial", "airline"), 3),
        (("customer",), 1),
        (("buyer",), 2),
    ),
    "acquisitions": (
        (("acquisition",), 3),
        (("business", "combination"), 3),
        (("acquired",), 2),
    ),
    "geography": (
        (("united", "states"), 3),
        (("europe",), 2),
        (("asia",), 2),
        (("geographic",), 2),
        (("segment",), 1),
    ),
    "products": ((("product",), 1), (("service",), 1), (("offering",), 1)),
    "segments": ((("segment",), 2), (("reportable", "segment"), 3)),
    "capital_return": (
        (("share", "repurchase"), 4),
        (("dividend",), 3),
        (("common", "stock"), 1),
    ),
    "retention": ((("retain",), 4), (("churn",), 3)),
    "restructuring": ((("restructuring",), 3), (("impairment",), 2)),
    "legal": (
        (("legal", "proceeding"), 4),
        (("litigation",), 3),
        (("claim",), 2),
        (("contingenc",), 2),
    ),
    "ppe": ((("property", "plant"), 4), (("plant", "equipment"), 3)),
    "change": ((("driven",), 2), (("increase",), 1), (("decrease",), 1), (("primarily",), 1)),
}

_STATEMENT_PHRASES: dict[str, tuple[str, ...]] = {
    "income": (
        "statement of income",
        "statements of income",
        "statement of operations",
        "statements of operations",
        "statement of earnings",
        "statements of earnings",
        "statement of loss",
        "statements of loss",
        "income statement",
        "statements of profit",
        "statement of profit",
    ),
    "cashflow": ("statement of cash flows", "statements of cash flows", "cash flows statement"),
    "balance": (
        "balance sheet",
        "balance sheets",
        "statement of financial position",
        "statements of financial position",
    ),
    "equity": (
        "statement of equity",
        "statements of equity",
        "statement of stockholders",
        "statements of stockholders",
        "statement of shareholders",
        "statements of shareholders",
    ),
    "segment": (
        "segment information",
        "business segment data",
        "summary of business segment data",
        "reportable segment",
        "reportable segments",
        "segment results",
        "segments",
    ),
    "analysis": (
        "management's discussion and analysis",
        "results of operations",
        "analysis of consolidated",
        "analysis of financial condition",
        "business environment",
        "executive overview",
        "financial review",
        "overview",
    ),
    "summary": (
        "summary of financial performance",
        "selected financial data",
        "five-year summary",
        "five year summary",
    ),
    "risk": ("risk factors",),
    "business": ("item 1. business", "item 1 business", "business overview", "our business"),
    "properties": ("item 2. properties", "item 2 properties"),
}
_NOTE_PHRASES: dict[str, tuple[str, ...]] = {
    "debt_note": ("debt outstanding", "long-term debt", "long term debt", "notes payable", "borrowings"),
    "acquisitions_note": ("acquisitions and divestitures", "business combinations", "acquisitions"),
    "legal_note": ("legal proceedings", "commitments and contingencies", "contingencies"),
    "tax_note": ("income taxes", "income tax"),
    "ppne_note": ("property, plant and equipment", "property plant and equipment"),
    "restructuring_note": ("restructuring",),
    "inventory_note": ("inventories",),
    "customer_note": ("customer", "concentration"),
    "capital_return_note": ("dividends", "repurchase"),
}
_RISK_PAGE_PHRASES = ("risk factors",)
_COVER_PHRASES = (
    "securities registered",
    "trading symbol",
    "registered pursuant",
    "united states securities and exchange",
)
_GEOGRAPHY_HEADING = re.compile(
    r"^(?:geographic operations|geographic information|geographic areas?|geographic regions?|"
    r"operations by geography|revenues? by geography|geographic segment)\b"
)
_CAPITAL_HEADING = re.compile(
    r"^(?:capital expenditures(?: and investments)?|capital spending|purchases of property)\b"
)
_SECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:part\s+[ivx]+\.?\s+)?item\s+1\.\s*business\.?$"), "business"),
    (re.compile(r"^(?:part\s+[ivx]+\.?\s+)?item\s+1a\.\s*risk factors\.?$"), "risk"),
    (re.compile(r"^(?:part\s+[ivx]+\.?\s+)?item\s+2\.\s*properties\.?$"), "properties"),
    (re.compile(r"^(?:part\s+[ivx]+\.?\s+)?item\s+3\.\s*legal proceedings\.?$"), "legal_note"),
)
_INDEX_HEADING_PHRASES = (
    "index to consolidated financial statements",
    "index to financial statements",
    "index to exhibits",
    "exhibit index",
    "financial statement schedules",
)
_REGION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bunited states\b",
        r"\bcanada\b",
        r"\bmexico\b",
        r"\blatin america\b",
        r"\bsouth america\b",
        r"\bbrazil\b",
        r"\beurope\b",
        r"\bemea\b",
        r"\bmiddle east\b",
        r"\bafrica\b",
        r"\bsouth asia\b",
        r"\basia pacific\b",
        r"\bapac\b",
        r"\bchina\b",
        r"\bjapan\b",
        r"\bindia\b",
        r"\baustralia\b",
        r"\bnew zealand\b",
        r"\bunited kingdom\b",
        r"\bgermany\b",
        r"\bfrance\b",
        r"\bitaly\b",
        r"\bspain\b",
        r"\brussia\b",
        r"\bcaribbean\b",
        r"\bnorth america\b",
        r"\bcountr(?:y|ies)\b",
        r"\bworldwide\b",
        r"\bgeograph",
    )
)
_LEGAL_PATTERN = re.compile(
    r"\b(?:litigation|lawsuits?|legal proceedings?|claims?|courts?|plaintiffs?|defendants?|settlements?|"
    r"subpoenas?|damages|class actions?|judgments?|attorneys? general|investigations?|contingenc(?:y|ies)|"
    r"regulatory proceedings?)\b",
    re.IGNORECASE,
)
_CUSTOMER_PATTERNS = tuple(
    (re.compile(pattern, re.IGNORECASE), weight)
    for pattern, weight in (
        (r"\bcustomers?\b[^.]{0,60}\b(?:accounted|represent|generated|comprised)\b", 2.0),
        (r"\b(?:one|two|three|four|five|\d+)\s+(?:customers?|clients?)\b", 1.5),
        (
            r"\b(?:significant|substantial|large|limited)\s+(?:portion|number|amount)\b[^.]{0,80}"
            r"\b(?:revenues?|sales|customers?|airlines?|government)\b",
            2.0,
        ),
        (
            r"\b\d{1,2}(?:\.\d+)?\s*%\s+of\s+(?:our|its|the company'?s?)\b[^.]{0,50}"
            r"\b(?:revenues?|sales)\b",
            2.0,
        ),
        (r"\b(?:united states|u\.s\.)\s+government\b", 1.5),
        (r"\bcommercial airlines?\b", 1.5),
        (r"\bcustomer concentration\b", 2.0),
    )
)


def _preprocess(text: str) -> str:
    for pattern, replacement in _PREPROCESS:
        text = pattern.sub(replacement, text)
    return text


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


def _normalize_token(raw: str) -> str:
    mapped = _CANONICAL.get(raw)
    return _stem(raw) if mapped is None else mapped


def _content_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for raw in _TOKEN_PATTERN.findall(_preprocess(text.lower()))
        if (token := _normalize_token(raw)) not in _STOPWORDS
    )


def _ngrams(tokens: tuple[str, ...], size: int) -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1))


def _text_lines(text: str) -> tuple[str, ...]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.lower().split())
        if not line:
            continue
        lines.append(line)
        if line.startswith("consolidated "):
            lines.append(line[13:])
    return tuple(lines)


def _strip_note(line: str) -> str:
    return re.sub(r"^note\s+\d+[a-z]?\s*[—\-:.]?\s*", "", line)


def _page_types(header: tuple[str, ...]) -> frozenset[str]:  # noqa: C901 - one branch per heading family
    head = header[:12]
    types: set[str] = set()
    for kind, phrases in _STATEMENT_PHRASES.items():
        if any(line.startswith(phrase) for line in head for phrase in phrases):
            types.add(kind)
    for kind, phrases in _NOTE_PHRASES.items():
        if any(line.startswith(phrase) or _strip_note(line).startswith(phrase) for line in head for phrase in phrases):
            types.add(kind)
    joined = "\n".join(head)
    if any(phrase in joined for phrase in _RISK_PAGE_PHRASES):
        types.add("risk")
    if any(phrase in joined for phrase in _COVER_PHRASES):
        types.add("cover")
    if "management" in joined and "discussion" in joined:
        types.add("analysis")
        types.add("mda")
    if "results of operations" in joined:
        types.add("analysis")
    for line in header:
        if len(line) > 110:
            continue
        if _GEOGRAPHY_HEADING.match(line):
            types.add("geography")
        if _CAPITAL_HEADING.match(line):
            types.add("capital_spend")
        for pattern, kind in _SECTION_PATTERNS:
            if pattern.match(line):
                types.add(kind)
    return frozenset(types)


def _region_hits(text: str) -> int:
    lowered = text.lower()
    return sum(1 for pattern in _REGION_PATTERNS if pattern.search(lowered))


def _legal_hits(text: str) -> int:
    return len(_LEGAL_PATTERN.findall(text))


def _customer_hits(text: str) -> float:
    return sum(weight for pattern, weight in _CUSTOMER_PATTERNS if pattern.search(text))


def _looks_like_index(text: str) -> bool:
    lines = text.splitlines()
    head = " ".join(" ".join(line.lower().split()) for line in lines[:14])
    if "exhibit index" in head:
        return True
    entries = 0
    for line in lines:
        stripped = " ".join(line.strip().split())
        match = _INDEX_LINE_PATTERN.search(stripped)
        if match is None or len(stripped) < 12:
            continue
        body = stripped[: match.start()].lower()
        if "$" in body or "%" in body:
            continue
        if not re.search(r"(?:statement|balance sheet|notes to|report of|item \d|part [ivx]|exhibit)", body):
            continue
        if len(body.split()) < 3:
            continue
        entries += 1
    return entries >= 3


@dataclass(frozen=True, slots=True)
class _PageFeatures:
    tokens: tuple[str, ...]
    bigrams: frozenset[tuple[str, ...]]
    trigrams: frozenset[tuple[str, ...]]
    types: frozenset[str]
    is_index: bool
    length: int
    regions: int
    legal: int
    customers: float


_FEATURE_CACHE: dict[tuple[tuple[str, int], str], _PageFeatures] = {}
_FEATURE_CACHE_LIMIT = 8192


@dataclass(frozen=True, slots=True)
class _PageRecord:
    citation: MemoryCitation
    entry_version_id: str
    tokens: tuple[str, ...]
    bigrams: frozenset[tuple[str, ...]]
    trigrams: frozenset[tuple[str, ...]]
    location: tuple[str, int]
    types: frozenset[str]
    is_index: bool
    length: int
    regions: int
    legal: int
    customers: float


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
    key = (location, entry.entry_version_id)
    features = _FEATURE_CACHE.get(key)
    if features is None:
        tokens = _content_tokens(text)
        features = _PageFeatures(
            tokens=tokens,
            bigrams=_ngrams(tokens, 2),
            trigrams=_ngrams(tokens, 3),
            types=_page_types(_text_lines(text)),
            is_index=_looks_like_index(text),
            length=len(tokens),
            regions=_region_hits(text),
            legal=_legal_hits(text),
            customers=_customer_hits(text),
        )
        if len(_FEATURE_CACHE) >= _FEATURE_CACHE_LIMIT:
            _FEATURE_CACHE.clear()
        _FEATURE_CACHE[key] = features
    return _PageRecord(
        citation=record.citation,
        entry_version_id=entry.entry_version_id,
        location=location,
        tokens=features.tokens,
        bigrams=features.bigrams,
        trigrams=features.trigrams,
        types=features.types,
        is_index=features.is_index,
        length=features.length,
        regions=features.regions,
        legal=features.legal,
        customers=features.customers,
    )


_STOPWORDS = frozenset(_normalize_token(word) for word in _STOPWORDS_WORDS)


def _detect_intents(question: str) -> frozenset[str]:
    lowered = _preprocess(question.lower())
    raw = question.lower()
    intents: set[str] = set()
    for intent, terms in _INTENT_TERMS.items():
        if any(term in lowered or term in raw for term in terms):
            intents.add(intent)
    if "cash flow" in lowered or "cash flows" in lowered:
        intents.add("cashflow")
    if "balance sheet" in lowered or "statement of financial position" in lowered or "financial position" in lowered:
        intents.add("balance")
    if any(
        phrase in lowered
        for phrase in (
            "income statement",
            "statement of income",
            "statements of income",
            "statement of operations",
            "statements of operations",
            "statement of earnings",
        )
    ):
        intents.add("income")
    if any(phrase in lowered for phrase in ("legal", "litigation", "lawsuit", "legal battle")):
        intents.add("legal")
    return frozenset(intents)


def _query_weights(
    question: str,
) -> tuple[dict[str, float], frozenset[tuple[str, ...]], frozenset[tuple[str, ...]], frozenset[str]]:
    tokens = _content_tokens(question)
    weights = {token: float(min(count, 3)) for token, count in Counter(tokens).items()}
    raw = question.lower()
    if re.search(r"\bppne\b", raw):
        for token in ("property", "plant", "equipment"):
            weights[token] = max(weights.get(token, 0.0), 1.4)
    if re.search(r"\bm\s*&\s*a\b", raw):
        weights["acquisition"] = max(weights.get("acquisition", 0.0), 1.5)
    if re.search(r"\bcapex\b", raw):
        for token in ("capital", "expenditure", "purchase"):
            weights[token] = max(weights.get(token, 0.0), 1.2)
    return (
        weights,
        _ngrams(tokens, 2),
        _ngrams(tokens, 3),
        _detect_intents(question),
    )


def _score(  # noqa: C901 - lexical, phrase, and page-type signals stay in one ranking pass
    records: list[_PageRecord],
    question: str,
) -> list[tuple[float, _PageRecord]]:
    weights, query_bigrams, query_trigrams, intents = _query_weights(question)
    document_count = len(records)
    average_length = sum(record.length for record in records) / document_count
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
    boosts: dict[str, float] = {}
    for intent in intents:
        for kind, value in _INTENT_BOOSTS.get(intent, {}).items():
            boosts[kind] = max(boosts.get(kind, 0.0), value)
    phrases: list[tuple[tuple[str, ...], float]] = []
    for intent in intents:
        phrases.extend(_INTENT_PHRASES.get(intent, ()))
    scored: list[tuple[float, _PageRecord]] = []
    for record in records:
        frequencies = Counter(record.tokens)
        score = 0.0
        for term, weight in weights.items():
            frequency = frequencies.get(term, 0)
            if frequency:
                score += (
                    weight
                    * idf[term]
                    * frequency
                    * (k1 + 1.0)
                    / (frequency + k1 * (1.0 - b + b * record.length / average_length))
                )
        score += 0.8 * len(query_bigrams & record.bigrams)
        score += 1.2 * len(query_trigrams & record.trigrams)
        for ngram, bonus in phrases:
            if (len(ngram) == 2 and ngram in record.bigrams) or (len(ngram) == 3 and ngram in record.trigrams):
                score += bonus
        if record.is_index:
            score -= 30.0
        else:
            for kind, bonus in boosts.items():
                if kind in record.types:
                    score += bonus
            if "geography" in intents:
                score += 1.2 * min(record.regions, 10)
            if "legal" in intents:
                score += 0.75 * min(record.legal, 24)
            if "customers" in intents:
                score += min(record.customers, 10)
            if record.length < 25:
                score -= 2.0
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
    page = await memory.search(SearchMemoryRequest(query=question, mode="auto", limit=max(limit, 40)))
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
