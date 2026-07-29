"""
app_web/server.py — Vanilla JS frontend for Agentic GraphRAG.

A thin FastAPI server that:
  • Serves the static vanilla JS UI at  /
  • Exposes POST /api/query → runs the agent workflow and returns JSON
  • Exposes GET  /api/examples → list of example queries

Run:
    python -m app_web.server
or
    uvicorn app_web.server:app --reload --host 0.0.0.0 --port 8001

The existing Streamlit interface in `app/streamlit_app.py` is untouched.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Make project root importable when running as `python -m app_web.server`
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.core.state import AgentState, BookNode, RECOMMEND_TOP_K
from app_web.agent_control import CONTROL
from app_web.examples import EXAMPLE_QUERIES
from app_web.query_log import QueryLog
from app_web.response_cache import ResponseCache

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

logger = logging.getLogger("app_web.server")

# ── App ────────────────────────────────────────────────────────────────
PLACEHOLDER_COVER = (
    "https://kios-perpustakaan.jakarta.go.id/assets/img/no-images-jaklitera.png"
)

# The bronze pipeline stores this base path (…/Monograf/ with no filename) as the
# cover_url for books that have NO cover — a broken image URL. ~16% of the catalog
# is in this state. Real covers are the ingested full URL and already carry the
# correct extension (jpg/png/jpeg/gif vary per book), so we trust the ingested
# value and only rewrite the filename-less sentinel to the placeholder.
_COVER_BASE = (
    "https://perpustakaan.jakarta.go.id/catalog-dispusip/"
    "uploaded_files/sampul_koleksi/original/Monograf/"
)


def _resolve_cover_url(raw: str | None) -> str:
    """Return a displayable cover URL, or the placeholder when the book has none."""
    if not raw:
        return PLACEHOLDER_COVER
    url = raw.strip()
    # Empty, the bare base path, or any URL with no filename after the last '/'.
    if not url or url.rstrip("/") == _COVER_BASE.rstrip("/") or url.endswith("/"):
        return PLACEHOLDER_COVER
    return url

app = FastAPI(title="Agentic GraphRAG — Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Full-response cache (answer + book cards + meta) so repeat queries skip the
# ~40s workflow, plus an append-only query log for latency/usage analysis.
_response_cache = ResponseCache()
_query_log = QueryLog()


# ── Schemas ────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    use_cache: bool = Field(default=True)


class BookCard(BaseModel):
    book_id: str
    title: str
    authors: list[str]
    categories: list[str]
    vibes: list[str]
    settings: list[str]
    available_at: list[str]
    is_available: bool
    relevance_score: float
    cover_url: str
    pub_year: int | None = None
    synopsis: str | None = None


class QueryResponse(BaseModel):
    answer: str
    books: list[BookCard]
    elapsed: float
    from_cache: bool
    intent: str | None = None
    query_type: str | None = None
    hop: int = 1
    traversal: list[str] = Field(default_factory=list)
    tool_chain: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    error: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────
def _book_to_card(book: BookNode) -> BookCard:
    cover = _resolve_cover_url(book.cover_url)
    return BookCard(
        book_id=book.book_id,
        title=book.title or "Untitled",
        authors=book.author_names or [],
        categories=[c.name for c in (book.categories or [])],
        vibes=book.vibe_names or [],
        settings=book.setting_names or [],
        available_at=book.available_at or [],
        is_available=book.is_available,
        relevance_score=float(book.relevance_score),
        cover_url=cover,
        pub_year=book.pub_year,
        synopsis=(book.abstract_clean or None),
    )


def _state_to_response(
    state: AgentState, elapsed: float, *, from_cache: bool
) -> QueryResponse:
    books = [_book_to_card(b) for b in (state.curated_context or [])][:RECOMMEND_TOP_K]

    traversal: list[str] = []
    if state.graph_intent:
        traversal = list(state.graph_intent.traversal_order)
        if state.graph_intent.branch_filter:
            traversal.append(f"Branch: {state.graph_intent.branch_filter}")

    # query_type: the router's front-door decision ("vector"/"graph"), falling
    # back to the Reasoner-assigned intent. hop: number of graph traversal steps
    # (vector-only answers are single-hop by definition).
    query_type = getattr(state, "route", None) or state.intent or None
    hop = max(1, len(state.graph_intent.traversal_order)) if state.graph_intent else 1

    return QueryResponse(
        answer=state.final_answer or "",
        books=books,
        elapsed=elapsed,
        from_cache=from_cache,
        intent=state.intent or None,
        query_type=query_type,
        hop=hop,
        traversal=traversal,
        tool_chain=list(state.tool_chain_log or []),
        reasoning=list(state.reasoning_log or []),
        violations=[str(v) for v in (state.violations or [])],
        error=state.error,
    )


# ── Routes ─────────────────────────────────────────────────────────────
@app.get("/")
def index() -> dict[str, Any]:
    """API root — the UI is the separate React app in frontend/."""
    return {
        "service": "Agentic GraphRAG — Web API",
        "ui": "React app in frontend/ (dev: http://localhost:5173)",
        "endpoints": [
            "/api/query", "/api/examples", "/api/health",
            "/api/modes", "/api/mode", "/api/cache/stats", "/api/cache/clear",
        ],
    }


@app.get("/api/examples")
def get_examples() -> dict[str, list[str]]:
    return {"examples": list(EXAMPLE_QUERIES)}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": os.getenv("ACTIVE_LLM_PROVIDER", "ollama"),
        "model": CONTROL.model,
        "mode": CONTROL.mode,
    }


@app.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    text = (req.query or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="query must not be empty")

    # Cache/log are namespaced per (mode, model) so a switch never serves
    # another config's answer for the same query text.
    ns = CONTROL.namespace()

    # ── Cache hit: return the full stored response instantly ──────────────
    if req.use_cache:
        hit = _response_cache.get(text, namespace=ns)
        if hit is not None:
            logger.info("Cache hit [%s]: %r", ns, text)
            response = QueryResponse(**{**hit, "from_cache": True})
            _query_log.append({
                "query": text,
                "mode": CONTROL.mode,
                "model": CONTROL.model,
                "from_cache": True,
                "elapsed": response.elapsed,
                "n_books": len(response.books),
                "query_type": response.query_type,
                "hop": response.hop,
                "error": response.error,
            })
            return response

    # ── Cache miss: run the *currently selected* workflow, serialized so a
    #    mode/model switch can't land mid-query. ──────────────────────────
    with CONTROL.lock:
        mode, model = CONTROL.mode, CONTROL.model
        ns = CONTROL.namespace()
        runner = CONTROL.get_runner()
        start = time.time()
        try:
            state = runner(text)
        except Exception as exc:  # pragma: no cover — surface to client
            logger.exception("Workflow crashed [mode=%s model=%s]", mode, model)
            _query_log.append({"query": text, "mode": mode, "model": model,
                               "from_cache": False, "error": str(exc)})
            raise HTTPException(status_code=500, detail=f"workflow error: {exc}") from exc
        elapsed = time.time() - start

    response = _state_to_response(state, elapsed, from_cache=False)

    # Cache only successful, non-empty results: transient LLM parse-fails can
    # yield 0 books, and we don't want to lock those in — a retry may do better.
    if req.use_cache and not response.error and response.books:
        _response_cache.set(text, response.model_dump(), namespace=ns)

    _query_log.append({
        "query": text,
        "mode": mode,
        "model": model,
        "from_cache": False,
        "elapsed": round(elapsed, 2),
        "n_books": len(response.books),
        "query_type": response.query_type,
        "hop": response.hop,
        "n_violations": len(response.violations),
        "error": response.error,
    })
    return response


# ── Admin: workflow mode + LLM model ─────────────────────────────────────
class ModeRequest(BaseModel):
    mode: str | None = None
    model: str | None = None


@app.get("/api/modes")
def get_modes() -> dict[str, Any]:
    """Available workflow modes + models, and the current selection."""
    return CONTROL.snapshot()


@app.post("/api/mode")
def set_mode(req: ModeRequest) -> dict[str, Any]:
    """Switch workflow mode and/or LLM model (model switch evicts VRAM)."""
    if req.mode is None and req.model is None:
        raise HTTPException(status_code=400, detail="provide 'mode' and/or 'model'")
    try:
        snap = CONTROL.switch(mode=req.mode, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Switched → mode=%s model=%s", snap["current_mode"], snap["current_model"])
    return snap


@app.get("/api/cache/stats")
def cache_stats() -> dict[str, Any]:
    """Hit/miss counters (this process) + number of cached queries."""
    return {"cache": _response_cache.stats()}


@app.post("/api/cache/clear")
def cache_clear() -> dict[str, Any]:
    """Drop all cached responses (e.g. after re-ingesting the graph)."""
    _response_cache.clear()
    return {"status": "cleared", "entries": _response_cache.size()}


# ── Entrypoint ─────────────────────────────────────────────────────────
def main() -> None:
    import uvicorn

    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8001"))
    logger.info("Starting web UI on http://%s:%d", host, port)
    uvicorn.run("app_web.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
