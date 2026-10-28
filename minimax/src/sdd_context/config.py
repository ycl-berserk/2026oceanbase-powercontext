"""运行配置：路径、数据库与 PowerContext 地址。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).resolve() if value else default.resolve()


@dataclass(frozen=True)
class Settings:
    root: Path
    project: Path
    db_path: Path
    powercontext_url: str
    powercontext_timeout: float

    @classmethod
    def load(cls, project: str | Path | None = None) -> Settings:
        root = _path("SDD_ROOT", PACKAGE_ROOT)
        project_path = (
            Path(project).resolve()
            if project
            else _path("SDD_PROJECT", root / "workspace")
        )
        db_path = _path("SDD_DB_PATH", root / "data" / "seekdb" / "sdd.db")
        timeout_value = os.environ.get("SDD_POWERCONTEXT_TIMEOUT", "8").strip() or "8"
        return cls(
            root=root,
            project=project_path,
            db_path=db_path,
            powercontext_url=os.environ.get(
                "SDD_POWERCONTEXT_URL", "http://127.0.0.1:8102"
            ).rstrip("/"),
            powercontext_timeout=float(timeout_value),
        )

    def relative(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.project).as_posix()
