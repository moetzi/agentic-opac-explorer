"""
app_web/query_log.py — append-only log of every web query.
──────────────────────────────────────────────────────────
One JSON object per line (JSONL): timestamp, query, from_cache, elapsed,
n_books, query_type, hop, n_violations, error. Useful for latency analysis
and seeing which queries users actually ask (thesis evaluation).

Append-only and best-effort: logging never raises into the request path.

Path overridable via AGENTIC_GRAPHRAG_QUERY_LOG.
Default: <project_root>/.streamlit_sessions/web_query_log.jsonl
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    override = os.getenv("AGENTIC_GRAPHRAG_QUERY_LOG")
    if override:
        return Path(override)
    root = Path(__file__).resolve().parent.parent
    return root / ".streamlit_sessions" / "web_query_log.jsonl"


class QueryLog:
    """Best-effort JSONL appender, one line per query."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path: Path = Path(path) if path else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        line = {"ts": datetime.now().isoformat(timespec="seconds"), **record}
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass
