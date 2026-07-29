"""
agent/tools/vector_tool.py — Semantic Vector Search (Front-Door)
──────────────────────────────────────────────────────────────────
Pakai SentenceTransformer (LazarusNLP E5) + Neo4j vector index secara LANGSUNG
(bypass `neo4j-graphrag.VectorRetriever` yang ternyata return 0 di environment
ini meskipun index ONLINE & populated).

`vector_search` adalah SALAH SATU tool retrieval yang dipilih reasoner/planner
di fase expand (dieksekusi lewat tool_executor_node → VECTOR_TOOLS branch) pada
arsitektur Search-Space-Gated (workflow.py) & Planned — BUKAN front-door
tersendiri. (Desain lama "vector-gated v1" yang memanggilnya sebagai front-door
via router.py sudah dihapus.) Standard RAG memanggil VectorSearchTool.search()
ini langsung sebagai satu-satunya retrieval-nya.

Dua keputusan desain (sesuai permintaan):
1. INPUT/OUTPUT BERORIENTASI JUDUL. Free-text query di-encode + dikueri ke
   index, lalu mengembalikan kandidat lengkap dengan relasi ontologi sudah
   ter-enrich di satu round-trip Cypher.
2. JUDUL BERAGAM. Internal top-K diperbesar (DEFAULT=20) lalu di-dedup
   berdasarkan judul ter-normalisasi sebelum dipotong ke top-K final.
   Mencegah hasil "Hujan" muncul 4× karena ada banyak edisi.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from functools import lru_cache
from typing import List

import torch
from sentence_transformers import SentenceTransformer

from agent.core.state import BookNode, parse_book_nodes
from agent.services.database import execute_query

logger = logging.getLogger(__name__)


# Configurable via environment ----------------------------------------------
_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "LazarusNLP/all-indo-e5-small-v4")
_INDEX_NAME = os.getenv("VECTOR_INDEX_NAME", "book_vector_index")
_TOP_K_FINAL = int(os.getenv("VECTOR_TOP_K", "5"))
_TOP_K_RAW = int(os.getenv("VECTOR_TOP_K_RAW", "20"))   # over-fetch lalu dedup


# ── Singleton embedding model ──────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Return a cached SentenceTransformer; loaded only once per process."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"get_embedding_model: Memuat {_MODEL_NAME} di {device} (singleton)...")
    return SentenceTransformer(_MODEL_NAME, device=device)


# ── Title normalization for dedup ───────────────────────────────────────────
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE    = re.compile(r"\s+")
_EDITION_TAG_RE = re.compile(
    r"\b(jilid|vol|volume|edisi|cet|cetakan|seri|seri ke)\s*[\dIVXivx]+\b",
    re.IGNORECASE,
)


def _normalize_title(title: str) -> str:
    """
    Normalisasi judul untuk dedup. Buang aksen, punctuation, edition tag,
    lalu collapse whitespace.

    "Hujan : Cinta dan Air Mata"  →  "hujan cinta dan air mata"
    "Negeri 5 Menara - Jilid 2"   →  "negeri 5 menara"
    """
    t = title.strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _EDITION_TAG_RE.sub(" ", t)
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


# ── Cypher template ────────────────────────────────────────────────────────
_VECTOR_AND_ENRICH = """
CALL db.index.vector.queryNodes($index_name, $top_k, $qv)
YIELD node AS b, score
OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
WITH b, score,
     collect(DISTINCT {name: a.name, role: coalesce(a.role, 'penulis')}) AS authors,
     collect(DISTINCT {name: br.name}) AS branches,
     collect(DISTINCT {name: v.name})  AS vibes,
     collect(DISTINCT {name: s.name})  AS settings,
     collect(DISTINCT {name: c.name})  AS categories
RETURN
  properties(b) AS book,
  score,
  authors, branches, vibes, settings, categories
ORDER BY score DESC
"""


class VectorSearchTool:
    """Pencarian semantik E5 + Neo4j vector index, output sudah enriched."""

    def __init__(self, driver=None):
        # driver tidak dipakai langsung (kita pakai execute_query helper),
        # arg dipertahankan untuk kompatibilitas konstruktor.
        self.driver = driver
        self.model = get_embedding_model()

    # ── Public API ──────────────────────────────────────────────────────────

    def search(self, query: str, *, top_k: int | None = None,
               diversify_by_title: bool = True) -> List[BookNode]:
        """
        Lakukan semantic search.

        Args:
            query              : free-text user query (ID/EN ok).
            top_k              : jumlah kandidat unik final (default env VECTOR_TOP_K=5).
            diversify_by_title : jika True, dedup berdasarkan judul ter-normalisasi
                                 lalu potong ke top_k. Default True.
        """
        if not query or not query.strip():
            return []

        target_k = top_k or _TOP_K_FINAL
        raw_k = max(_TOP_K_RAW, target_k * 4)

        try:
            # E5 convention: prefix "query: " untuk pertanyaan pengguna.
            query_vector = self.model.encode(f"query: {query}").tolist()

            raw_results = execute_query(
                _VECTOR_AND_ENRICH,
                {"index_name": _INDEX_NAME, "top_k": raw_k, "qv": query_vector},
            )
            if not raw_results:
                logger.info("VectorTool: 0 kandidat untuk '%s'.", query[:60])
                return []

            # Suntikkan score ke `book.relevance_score` agar konsisten dgn parser.
            for r in raw_results:
                if "book" in r and isinstance(r["book"], dict):
                    r["book"]["relevance_score"] = float(r.get("score") or 0.0)

            books = parse_book_nodes(raw_results)

            if diversify_by_title:
                books = self._dedup_by_title(books, target_k)
            else:
                books = books[:target_k]

            books.sort(key=lambda b: b.relevance_score, reverse=True)
            return books

        except Exception as exc:
            logger.error("VectorSearchTool error: %s", exc, exc_info=True)
            return []

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _dedup_by_title(books: list[BookNode], target_k: int) -> list[BookNode]:
        """
        Dedup berdasarkan judul ter-normalisasi. Jika ada beberapa book_id
        dengan judul mirip, ambil yang skor tertinggi.
        """
        seen: dict[str, BookNode] = {}
        # books sudah ORDER BY score DESC dari Cypher; iterate sambil dedup.
        for b in books:
            key = _normalize_title(b.title)
            if not key:
                continue
            if key not in seen:
                seen[key] = b
            if len(seen) >= target_k:
                break
        return list(seen.values())
