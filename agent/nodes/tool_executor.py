"""
Node 2/3 — Tool Executor (The Hands of the Search-Space-Gated ReAct Loop)
─────────────────────────────────────────────────────────────────────
Generic dispatcher over agent/tools/tools_catalog.py's CYPHER_TOOLS: no
per-tool Python wrapper functions — given a tool name + args, fill in the
declared "params" from args (with a few sane auto-defaults like book_ids
defaulting to the current pool), run "cypher" via execute_query, then merge
the result into the pool according to its kind:

  - FILTER_TOOLS (filter_by_branch/_collection_type/_language): narrow the
    pool to the matching subset (intersection), keep existing relation data.
    Guarded against wiping a non-empty pool to zero — an ungrounded filter
    call from the reasoner is reported as 0 results (tagged with
    DESTRUCTIVE_FILTER_TAG, parsed by evaluation/metrics.py) instead of
    destroying every candidate gathered so far.
  - NON_BOOK_TOOLS (categories_by_author): never touch the pool, surfaced
    via observation text only.
  - VECTOR_TOOLS (vector_search): bypasses execute_query() — calls
    VectorSearchTool.search() instead, merges results the same way as a
    seed/multihop lookup. Reachable from any workflow that exposes it in the
    reasoner/planner action space — Search-Space-Gated's expand phase
    (EXPAND_TOOLS), pure-ReAct/act-only, and Planned (PURE_REACT_TOOLS) all do.
  - everything else (seed/multihop lookups): merge into the pool — union
    relations, keep the higher score (+ small per-tool boost).

Tidak ada keputusan strategis di sini. Semua logika "apa yang harus dipanggil
selanjutnya" ada di Reasoner.
"""

from __future__ import annotations

import logging

from agent.core.state import AgentState, parse_book_nodes
from agent.services.database import execute_query
from agent.tools import CYPHER_TOOLS, FILTER_TOOLS, NON_BOOK_TOOLS, VECTOR_TOOLS

logger = logging.getLogger(__name__)

# Substring tagged onto the observation when a filter call is overridden
# (see tool_executor_node's FILTER_TOOLS branch) — evaluation/metrics.py
# greps tool_chain_log for this to count hallucinated/ungrounded filter
# calls that tool_set_match's recall-only formula can't otherwise see.
DESTRUCTIVE_FILTER_TAG = "filter diabaikan, pool dipertahankan"

# Lazy singleton — only loaded the first time a workflow actually dispatches
# "vector_search" through this node (Search-Space-Gated expand phase, pure-ReAct/
# act-only, or Planned — all expose it in the reasoner/planner action space).
# Standard RAG calls VectorSearchTool directly instead of going through here.
_vector_tool = None


def _get_vector_tool():
    global _vector_tool
    if _vector_tool is None:
        from agent.tools.vector_tool import VectorSearchTool
        _vector_tool = VectorSearchTool()
    return _vector_tool


# ══════════════════════════════════════════════════════════════
# POOL HELPERS
# ══════════════════════════════════════════════════════════════

def _book_nodes_to_pool(nodes) -> dict[str, dict]:
    """Convert state.enriched_data (list[BookNode]) → internal pool dict."""
    pool: dict[str, dict] = {}
    for b in nodes:
        # bungkus seperti format Neo4j {"book": {...}, "authors": [...], ...}
        pool[b.book_id] = {
            "book": {
                "book_id": b.book_id,
                "title": b.title,
                "isbn_13": b.isbn_13,
                "pub_year": b.pub_year,
                "total_pages": b.total_pages,
                "abstract_clean": b.abstract_clean,
                "is_fiction": b.is_fiction,
                "cover_url": b.cover_url,
                "ddc_class": b.ddc_class,
                "language": b.language,
                "edisi": b.edisi,
                "score": b.relevance_score,
                "relevance_score": b.relevance_score,
            },
            "authors":    [a.model_dump() for a in b.authors],
            "publisher":  b.publisher.model_dump() if b.publisher else None,
            "categories": [c.model_dump() for c in b.categories],
            "branches":   [br.model_dump() for br in b.branches],
            "vibes":      [v.model_dump() for v in b.vibes],
            "settings":   [s.model_dump() for s in b.settings],
            "characters": [c.model_dump() for c in b.characters],
        }
    return pool


def _result_book_id(raw: dict) -> str:
    book = raw.get("book") or raw
    return book.get("book_id") or book.get("id", "")


def _merge_results(pool: dict[str, dict], new_results: list[dict], boost: float = 0.0) -> dict[str, dict]:
    """Merge raw results ke pool; enrich relasi, ambil skor max + boost."""
    for raw in new_results:
        bid = _result_book_id(raw)
        if not bid:
            continue
        if bid in pool:
            for rel in ("authors", "vibes", "settings", "branches", "categories", "characters"):
                old_rel = pool[bid].get(rel) or []
                new_rel = raw.get(rel) or []
                merged = {
                    (r.get("name") if isinstance(r, dict) else r): (r if isinstance(r, dict) else {"name": r})
                    for r in old_rel + new_rel
                    if (r.get("name") if isinstance(r, dict) else r)
                }
                pool[bid][rel] = list(merged.values())

            old_score = (pool[bid].get("book") or pool[bid]).get("score", 0) or 0
            new_score = (raw.get("book") or raw).get("score", 0) or 0
            top_score = max(float(old_score), float(new_score)) + boost
            if "book" in pool[bid]:
                pool[bid]["book"]["score"] = top_score
                pool[bid]["book"]["relevance_score"] = top_score
            else:
                pool[bid]["score"] = top_score
        else:
            new_raw = dict(raw)
            if "book" in new_raw:
                new_raw["book"] = dict(new_raw["book"])
                base = float(new_raw["book"].get("score") or 0)
                new_raw["book"]["score"] = base + boost
                new_raw["book"]["relevance_score"] = base + boost
            pool[bid] = new_raw
    return pool


def _narrow_pool(pool: dict[str, dict], matched: list[dict], extra_rel: str | None = None) -> dict[str, dict]:
    """
    Untuk filter_by_*: tool mengembalikan hanya buku yang COCOK. Pool baru =
    irisan pool lama dengan id yang cocok, ditambah relasi baru (mis. branches)
    jika tool itu juga melaporkannya.
    """
    matched_by_id = {_result_book_id(r): r for r in matched if _result_book_id(r)}
    narrowed: dict[str, dict] = {}
    for bid, raw in matched_by_id.items():
        if bid not in pool:
            continue
        narrowed[bid] = pool[bid]
        if extra_rel and extra_rel in raw:
            narrowed[bid][extra_rel] = raw[extra_rel]
    return narrowed


# ══════════════════════════════════════════════════════════════
# PARAM BINDING
# ══════════════════════════════════════════════════════════════

_DEFAULT_TOP_K = 10

# Lantai relaksasi untuk search_similar_runtime. Default min_score=0.75 (di
# _bind_params) sengaja konservatif demi presisi, tapi buku rujukan berlingkungan
# jarang (mis. judul indie niche) bisa punya SELURUH tetangga terdekat aslinya
# tepat di bawah 0.75 — ranking-nya tetap benar, ambangnya saja yang salah
# kalibrasi (lih. Q97: top-5 tetangga benar di 0.73–0.7476, semua terpangkas →
# 0 hasil). Kalau 0.75 mengosongkan hasil, retry sekali di lantai ini menyelamatkan
# recall TANPA melonggarkan lingkungan padat (di sana tetangga asli 0.80–0.97 dan
# top_k tetap membatasi jumlahnya).
_SIMILARITY_MIN_SCORE_FLOOR = 0.70


def _bind_params(tool_name: str, args: dict, pool: dict[str, dict]) -> tuple[dict, str | None]:
    """
    Isi param yang dideklarasikan tool dari args, dengan auto-default untuk
    beberapa nama yang umum. Kembalikan (params, error_message). error_message
    None berarti sukses.
    """
    spec = CYPHER_TOOLS[tool_name]
    params: dict = {}
    for name in spec["params"]:
        if name in args:
            params[name] = args[name]
        elif name == "book_ids":
            if not pool:
                return {}, f"{tool_name} dilewati: pool masih kosong."
            params[name] = list(pool.keys())
        elif name == "top_k":
            params[name] = _DEFAULT_TOP_K
        elif name == "raw_k":
            params[name] = max(_DEFAULT_TOP_K * 5, 30)
        elif name == "min_score":
            params[name] = 0.75
        elif name == "titles" and "title" in args:
            params[name] = [args["title"]]
        else:
            return {}, f"{tool_name} butuh argumen '{name}'."
    return params, None


# ══════════════════════════════════════════════════════════════
# NODE
# ══════════════════════════════════════════════════════════════

def tool_executor_node(state: AgentState) -> AgentState:
    """Eksekusi state.next_action; merge/narrow pool; tulis observation."""
    if not state.scratchpad:
        return state.model_copy(update={
            "error": "tool_executor dipanggil tapi scratchpad kosong.",
        })

    last_step = state.scratchpad[-1]
    next_action = state.next_action or {}
    tool_name = next_action.get("tool") or last_step.action
    args = next_action.get("args") or last_step.action_input or {}

    if tool_name not in CYPHER_TOOLS:
        observation = f"Tool '{tool_name}' tidak terdaftar."
        updated_step = last_step.model_copy(update={"observation": observation})
        new_scratch = state.scratchpad[:-1] + [updated_step]
        return state.model_copy(update={
            "scratchpad":     new_scratch,
            "next_action":    None,
            "tool_chain_log": state.tool_chain_log + [f"tool_executor → ERROR: {observation}"],
        })

    pool = _book_nodes_to_pool(state.enriched_data)

    if tool_name in VECTOR_TOOLS:
        query_text = (args.get("query") or state.query or "").strip()
        try:
            vector_books = _get_vector_tool().search(query_text, top_k=_DEFAULT_TOP_K)
        except Exception as exc:
            logger.exception("tool_executor: vector_search failed: %s", exc)
            observation = f"ERROR saat menjalankan vector_search: {exc}"
            updated_step = last_step.model_copy(update={"observation": observation})
            new_scratch = state.scratchpad[:-1] + [updated_step]
            return state.model_copy(update={
                "scratchpad":     new_scratch,
                "next_action":    None,
                "tool_chain_log": state.tool_chain_log + [f"tool_executor → ERROR: vector_search ({exc})"],
            })

        raw_results = list(_book_nodes_to_pool(vector_books).values())
        n_new = len(raw_results)
        pool = _merge_results(pool, raw_results, boost=0.02)
        observation = f"vector_search({{'query': {query_text!r}}}) → {n_new} hasil (pool sekarang {len(pool)} buku)."
        enriched = parse_book_nodes(list(pool.values()))

        updated_step = last_step.model_copy(update={"observation": observation})
        new_scratch = state.scratchpad[:-1] + [updated_step]
        logger.info("tool_executor: vector_search → %s (pool=%d)", observation, len(enriched))
        return state.model_copy(update={
            "scratchpad":      new_scratch,
            "next_action":     None,
            "enriched_data":   enriched,
            "tool_chain_log":  state.tool_chain_log + [f"tool_executor → vector_search: {observation}"],
            "error":           None,
        })

    params, bind_error = _bind_params(tool_name, args, pool)

    if bind_error:
        updated_step = last_step.model_copy(update={"observation": bind_error})
        new_scratch = state.scratchpad[:-1] + [updated_step]
        return state.model_copy(update={
            "scratchpad":     new_scratch,
            "next_action":    None,
            "tool_chain_log": state.tool_chain_log + [f"tool_executor → {bind_error}"],
        })

    try:
        raw_results = execute_query(CYPHER_TOOLS[tool_name]["cypher"], params)
    except Exception as exc:
        logger.exception("tool_executor: '%s' failed: %s", tool_name, exc)
        observation = f"ERROR saat menjalankan {tool_name}: {exc}"
        updated_step = last_step.model_copy(update={"observation": observation})
        new_scratch = state.scratchpad[:-1] + [updated_step]
        return state.model_copy(update={
            "scratchpad":     new_scratch,
            "next_action":    None,
            "tool_chain_log": state.tool_chain_log + [f"tool_executor → ERROR: {tool_name} ({exc})"],
        })

    # ── search_similar_runtime: relaksasi ambang sekali kalau kosong ──────
    # Lihat _SIMILARITY_MIN_SCORE_FLOOR. Ranking KNN sudah benar; hanya ambang
    # 0.75 yang kadang terlalu ketat untuk buku rujukan berlingkungan jarang.
    sim_relaxed = False
    if (tool_name == "search_similar_runtime" and not raw_results
            and params.get("min_score", 0.0) > _SIMILARITY_MIN_SCORE_FLOOR):
        relaxed_params = dict(params, min_score=_SIMILARITY_MIN_SCORE_FLOOR)
        try:
            raw_results = execute_query(CYPHER_TOOLS[tool_name]["cypher"], relaxed_params)
        except Exception as exc:
            logger.warning("tool_executor: relaksasi search_similar_runtime gagal: %s", exc)
            raw_results = []
        if raw_results:
            sim_relaxed = True
            logger.info(
                "tool_executor: search_similar_runtime relaksasi min_score %.2f→%.2f, %d hasil",
                params.get("min_score", 0.0), _SIMILARITY_MIN_SCORE_FLOOR, len(raw_results),
            )

    # ── Merge semantics depend on tool kind ──────────────────────────────
    if tool_name in NON_BOOK_TOOLS:
        # categories_by_author: tidak menambah/mengubah pool, hanya teks.
        if not raw_results:
            observation = f'{tool_name}{args} → 0 hasil.'
        else:
            breakdown = ", ".join(
                f'{r.get("category")} ({r.get("book_count")})' for r in raw_results
            )
            observation = f'{tool_name}{args} → {breakdown}.'

    elif tool_name in FILTER_TOOLS:
        extra_rel = {
            "filter_by_author": "authors",
            "filter_by_branch": "branches",
            "filter_by_collection_type": "collection_types",
            "filter_by_language": "languages",
        }[tool_name]
        n_before = len(pool)
        narrowed = _narrow_pool(pool, raw_results, extra_rel=extra_rel)
        if n_before > 0 and not narrowed:
            # Ungrounded/wrong filter wiped out every candidate — ignore the
            # narrowing instead of leaving the pool empty for the rest of the
            # loop. Keeps "0/" in the observation so reasoner's repeated-
            # unproductive-action check still fires if it tries again.
            observation = f"{tool_name}{args} → 0/{n_before} buku lolos filter ({DESTRUCTIVE_FILTER_TAG})."
        else:
            pool = narrowed
            observation = f"{tool_name}{args} → {len(pool)}/{n_before} buku lolos filter."

    else:
        boost = 0.05 if tool_name in ("books_by_vibe_and_setting", "books_by_vibe_and_category",
                                       "books_by_setting_and_category", "books_by_author_and_vibe",
                                       "books_by_author_and_setting", "books_by_author_and_category",
                                       "books_by_ddc_and_branch", "books_by_vibe_and_branch",
                                       "books_by_category_and_branch", "books_by_collection_type_and_category",
                                       "books_by_vibe_and_setting_and_category") else 0.02
        n_new = len(raw_results)
        pool = _merge_results(pool, raw_results, boost=boost)
        relax_note = f" [min_score dilonggarkan ke {_SIMILARITY_MIN_SCORE_FLOOR}]" if sim_relaxed else ""
        observation = f"{tool_name}{args} → {n_new} hasil (pool sekarang {len(pool)} buku).{relax_note}"

    enriched = parse_book_nodes(list(pool.values()))

    updated_step = last_step.model_copy(update={"observation": observation})
    new_scratch = state.scratchpad[:-1] + [updated_step]

    logger.info("tool_executor: %s → %s (pool=%d)", tool_name, observation, len(enriched))

    return state.model_copy(update={
        "scratchpad":      new_scratch,
        "next_action":     None,
        "enriched_data":   enriched,
        "tool_chain_log":  state.tool_chain_log + [
            f"tool_executor → {tool_name}: {observation}"
        ],
        "error":           None,
    })
