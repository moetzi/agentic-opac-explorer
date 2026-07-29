"""
app_web/response_cache.py — full-response cache for the web API.
────────────────────────────────────────────────────────────────
Caches the *complete* /api/query JSON response — answer + book cards + meta —
keyed by the normalized query. A cache hit returns the full result instantly,
skipping the ~40s agent workflow for repeat queries.

Path overridable via AGENTIC_GRAPHRAG_WEB_CACHE.
Default: <project_root>/.streamlit_sessions/web_response_cache.json
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_WS_RE = re.compile(r"\s+")


def normalize_query(q: str) -> str:
    """Stable cache key from a user query: lowercase, NFKC-normalize, collapse
    internal whitespace, strip surrounding whitespace and a trailing '?'."""
    if q is None:
        return ""
    s = unicodedata.normalize("NFKC", str(q)).strip().lower()
    s = _WS_RE.sub(" ", s)
    return s.rstrip("?").strip()


def _default_path() -> Path:
    override = os.getenv("AGENTIC_GRAPHRAG_WEB_CACHE")
    if override:
        return Path(override)
    root = Path(__file__).resolve().parent.parent
    return root / ".streamlit_sessions" / "web_response_cache.json"


class ResponseCache:
    """File-backed cache of complete QueryResponse dicts, keyed by query."""

    def __init__(self, store_path: Path | str | None = None) -> None:
        self.store_path: Path = Path(store_path) if store_path else _default_path()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, dict[str, Any]] = self._load()
        self._hits: int = 0
        self._misses: int = 0

    # ── Persistence ───────────────────────────────────────────
    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.store_path.exists():
            return {}
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        try:
            self.store_path.write_text(
                json.dumps(self._entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ── Keying ────────────────────────────────────────────────
    @staticmethod
    def _key(query: str, namespace: str) -> str:
        """Cache key = namespace + normalized query. The namespace (e.g.
        "planned:qwen2.5:7b") keeps results from different workflow/model
        configs from colliding on the same query text."""
        return f"{namespace}\x1f{normalize_query(query)}"

    # ── Public API ────────────────────────────────────────────
    def get(self, query: str, namespace: str = "") -> Optional[dict[str, Any]]:
        """Return the cached response dict (bump hit counter), or None on miss."""
        entry = self._entries.get(self._key(query, namespace))
        if entry is None:
            self._misses += 1
            return None
        self._hits += 1
        return entry.get("response")

    def set(self, query: str, response: dict[str, Any], namespace: str = "") -> None:
        """Store/refresh the full response dict for `query` under `namespace`."""
        if not normalize_query(query):
            return
        self._entries[self._key(query, namespace)] = {
            "query": query,
            "namespace": namespace,
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            "response": response,
        }
        self._save()

    def remove(self, query: str, namespace: str = "") -> None:
        if self._entries.pop(self._key(query, namespace), None) is not None:
            self._save()

    def clear(self) -> None:
        self._entries.clear()
        self._save()
        self._hits = 0
        self._misses = 0

    # ── Stats ─────────────────────────────────────────────────
    def size(self) -> int:
        return len(self._entries)

    def keys(self) -> list[str]:
        return list(self._entries.keys())

    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "entries": self.size()}
