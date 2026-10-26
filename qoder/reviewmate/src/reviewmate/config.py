from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> None:
    """读取简单的 KEY=VALUE 配置，不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    root: Path
    db_path: Path
    embed_model: str
    embed_dim: int
    embed_cache: str | None
    top_k: int
    powercontext_url: str
    powercontext_timeout: float
    llm_provider: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str

    @property
    def web_dir(self) -> Path:
        return self.root / "web"

    @property
    def samples_dir(self) -> Path:
        return self.root / "data" / "samples"

    @property
    def llm_mode(self) -> str:
        provider = self.llm_provider.lower()
        if provider == "off":
            return "extractive"
        if provider in {"auto", "deepseek"} and self.deepseek_api_key:
            return "deepseek"
        return "extractive"

    @classmethod
    def load(cls, root: Path | None = None) -> Settings:
        root = Path(root or PROJECT_ROOT).resolve()
        load_dotenv(root / ".env")
        db_value = Path(_env("REVIEWMATE_DB_PATH", "data/seekdb/reviewmate.db"))
        db_path = db_value if db_value.is_absolute() else root / db_value
        cache = _env("REVIEWMATE_EMBED_CACHE", "")
        return cls(
            root=root,
            db_path=db_path,
            embed_model=_env("REVIEWMATE_EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
            embed_dim=_env_int("REVIEWMATE_EMBED_DIM", 512),
            embed_cache=cache or None,
            top_k=max(1, _env_int("REVIEWMATE_TOP_K", 6)),
            powercontext_url=_env("REVIEWMATE_POWERCONTEXT_URL", "http://127.0.0.1:8100").rstrip("/"),
            powercontext_timeout=_env_float("REVIEWMATE_POWERCONTEXT_TIMEOUT", 8.0),
            llm_provider=_env("REVIEWMATE_LLM_PROVIDER", "auto").lower(),
            deepseek_api_key=_env("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
        )
