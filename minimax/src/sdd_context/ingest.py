"""把规格、代码符号和测试导入 seekdb。"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .db import Doc, Store

SPEC_HEADING = re.compile(r"^###\s+(R\d+)\s+(.+?)\s*$")


def _rel(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project).as_posix()


def parse_specs(project: Path) -> list[Doc]:
    docs: list[Doc] = []
    for path in sorted((project / "specs").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        hits = [(index, match) for index, line in enumerate(lines) if (match := SPEC_HEADING.match(line))]
        for position, (line_no, match) in enumerate(hits):
            end = hits[position + 1][0] if position + 1 < len(hits) else len(lines)
            spec_id, title = match.group(1), match.group(2).strip()
            docs.append(
                Doc(
                    doc_key=f"spec:{path.stem}#{spec_id}",
                    kind="spec",
                    path=_rel(project, path),
                    symbol=spec_id,
                    heading=f"{spec_id} {title}",
                    content="\n".join(lines[line_no:end]).strip(),
                    start_line=line_no + 1,
                    end_line=end,
                )
            )
    return docs


def _symbols(node: ast.AST):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        yield node.name, node
    elif isinstance(node, ast.ClassDef):
        yield node.name, node
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{node.name}.{item.name}", item


def parse_code(project: Path) -> list[Doc]:
    docs: list[Doc] = []
    source_root = project / "src"
    for path in sorted(source_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        module = path.relative_to(source_root).with_suffix("").as_posix().replace("/", ".")
        for node in tree.body:
            for symbol, target in _symbols(node):
                segment = ast.get_source_segment(text, target) or ""
                docstring = ast.get_docstring(target) or ""
                docs.append(
                    Doc(
                        doc_key=f"code:{module}:{symbol}",
                        kind="code",
                        path=_rel(project, path),
                        symbol=symbol,
                        heading=symbol,
                        content=f"{path.name} {module} {symbol}\n{docstring}\n{segment}",
                        start_line=target.lineno,
                        end_line=target.end_lineno or target.lineno,
                    )
                )
    return docs


def parse_tests(project: Path) -> list[Doc]:
    docs: list[Doc] = []
    tests_root = project / "tests"
    for path in sorted(tests_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in tree.body:
            candidates: list[tuple[str, ast.AST]] = []
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                candidates.append((node.name, node))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                        candidates.append((f"{node.name}.{item.name}", item))
            for name, target in candidates:
                segment = ast.get_source_segment(text, target) or ""
                docstring = ast.get_docstring(target) or ""
                docs.append(
                    Doc(
                        doc_key=f"test:{_rel(project, path)}:{name}",
                        kind="test",
                        path=_rel(project, path),
                        symbol=name,
                        heading=name,
                        content=f"{path.name} {name}\n{docstring}\n{segment}",
                        start_line=target.lineno,
                        end_line=target.end_lineno or target.lineno,
                    )
                )
    return docs


def ingest(settings: Settings) -> dict[str, object]:
    project = settings.project
    docs = parse_specs(project) + parse_code(project) + parse_tests(project)
    with Store(settings.db_path) as store:
        store.clear()
        store.upsert(docs)
        counts = store.stats()
        store.set_meta("ingested_at", datetime.now(UTC).isoformat(timespec="seconds"))
        store.set_meta("project", str(project))
    return {
        "project": str(project),
        "db": str(settings.db_path),
        "counts": counts,
        "total": len(docs),
    }
