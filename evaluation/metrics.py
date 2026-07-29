"""
evaluation/metrics.py — Shared Evaluation Metrics (6-Metric Hybrid Framework)
──────────────────────────────────────────────────────────────────────────────
Modul metrik bersama untuk evaluasi Agentic GraphRAG book recommendation
system. Menggabungkan tiga kategori metrik:

  1. RETRIEVAL  — Precision@K
  2. GENERATION — (offline proxies; full RAGAS/LLM-as-Judge dijalankan
                   terpisah di ragas_evaluation.py)
  3. OPERATIONAL — Latency, Token Cost, Tool Set Match

Kenapa hybrid? Sistem rekomendasi buku tidak punya satu jawaban "benar" —
beberapa rekomendasi bisa sama-sama valid. Maka metrik standar factoid QA
(Exact Match) tidak cocok. Kita adaptasi:
  - Precision@K memakai expected_book_ids sebagai "relevant set" (bukan
    satu jawaban tunggal)
  - Tool Set Match memakai set intersection (order-independent) karena
    reasoner bisa memilih tool dalam urutan berbeda dan tetap benar.
  - Faithfulness & Answer Relevance di-delegasikan ke RAGAS (LLM judge)
    di fase terpisah.

Digunakan oleh:
  - evaluation/run_comparative_evaluation.py   (Phase 1: offline metrics)
  - evaluation/ragas_evaluation.py             (Phase 2: LLM-as-judge)
"""

from __future__ import annotations

import re
from typing import List, Optional

from agent.nodes.tool_executor import DESTRUCTIVE_FILTER_TAG


# ═══════════════════════════════════════════════════════════════
# 1. RETRIEVAL METRIC
# ═══════════════════════════════════════════════════════════════

def precision_at_k(
    retrieved_ids: list[str],
    expected_ids: list[str],
    k: int = 5,
) -> float:
    """
    Precision@K: proporsi dari top-K retrieved items yang relevan.

    Untuk book recommendation: expected_ids adalah kumpulan buku yang
    dianggap relevan oleh ground truth. Berbeda dari factoid QA yang hanya
    punya 1 jawaban benar, di sini "relevant set" bisa berisi banyak
    buku yang semuanya valid.

    Formula:
        P@K = |retrieved[:K] ∩ expected| / K

    Returns:
        float: Skor 0.0–1.0, atau -1.0 jika expected_ids kosong
               (artinya metrik ini tidak bisa dievaluasi untuk query ini).
    """
    if not expected_ids:
        return -1.0  # Tidak bisa dievaluasi (expected kosong)
    top_k = retrieved_ids[:k]
    hits = sum(1 for bid in top_k if bid in set(expected_ids))
    return round(hits / k, 4)


# ═══════════════════════════════════════════════════════════════
# 2. GENERATION METRICS (offline proxies)
#    Full RAGAS (Faithfulness, Answer Relevance) dijalankan terpisah
#    di ragas_evaluation.py dengan LLM judge.
# ═══════════════════════════════════════════════════════════════

def answer_contains_check(
    answer: str,
    required: list[str],
) -> float:
    """
    Offline proxy untuk Answer Relevance: berapa fraksi dari required
    terms yang ada di answer (case-insensitive keyword matching).

    Ini BUKAN pengganti RAGAS Answer Relevance (yang menggunakan
    reverse-engineered questions + semantic similarity), melainkan
    quick sanity check yang bisa dijalankan tanpa LLM judge.

    Args:
        answer:   Jawaban final dari pipeline.
        required: List of required keywords/phrases (dari ground truth
                  field `expected_answer_contains`).

    Returns:
        float: Skor 0.0–1.0 (fraksi keyword yang ditemukan).

    Catatan: pencocokan dilakukan setelah whitespace dinormalisasi (spasi
    ganda → satu spasi). Judul katalog banyak yang punya spasi ganda setelah
    titik dua (mis. "Reportase :  Panduan Praktis ...") sementara LLM menyalin
    dengan satu spasi — tanpa normalisasi, keyword semacam itu palsu-negatif.
    """
    if not required or not answer:
        return 0.0
    answer_norm = _normalize_ws(answer)
    hits = sum(1 for term in required if _normalize_ws(term) in answer_norm)
    return round(hits / len(required), 4)


_TITLE_QUOTE_RE = re.compile(r'["“”]([^"“”]{3,120})["“”]')


def _normalize_ws(text: str) -> str:
    """Collapse whitespace apa pun jadi satu spasi + lowercase, supaya judul
    dengan spasi ganda (mis. 'Reportase :  Panduan ...') tetap match."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def title_faithfulness(
    answer: str,
    curated_titles: list[str],
    query: str = "",
) -> float:
    """
    Offline proxy untuk RAGAS Faithfulness / groundedness (tanpa LLM judge).

    Mengukur berapa fraksi judul buku yang DIKUTIP di jawaban yang benar-benar
    tergrounding — yaitu ada di `curated_context` (hasil retrieval) ATAU
    disebut user di `query` (judul referensi pada query collaborative). Judul
    yang muncul di jawaban tapi tidak ada di dua sumber itu = halusinasi.

    Ini menutup blind spot `answer_contains_check`: pada kasus seperti qwen2.5
    Q92, model mengarang judul akademik ("Humanitarian Intervention: Legal,
    Moral and Political Issues") yang TIDAK ada di konteks, tapi
    `answer_contains` tetap 1.0 karena keyword query kebetulan cocok. Metrik
    ini akan menandainya < 1.0.

    Returns:
        float: 1.0 = semua judul yang disebut tergrounding (atau tidak ada
               judul yang dikutip → vacuously faithful). < 1.0 = ada judul
               karangan. -1.0 jika answer kosong (tidak bisa dievaluasi).
    """
    if not answer:
        return -1.0
    quoted = _TITLE_QUOTE_RE.findall(answer)
    if not quoted:
        return 1.0  # tidak ada klaim judul → tidak ada yang bisa dihalusinasi

    known = [_normalize_ws(t) for t in curated_titles if t]
    q_norm = _normalize_ws(query)

    grounded = 0
    for raw in quoted:
        cand = _normalize_ws(raw)
        in_context = any(cand in k or k in cand for k in known)
        in_query = bool(cand) and cand in q_norm  # judul referensi dari user
        if in_context or in_query:
            grounded += 1
    return round(grounded / len(quoted), 4)


# ═══════════════════════════════════════════════════════════════
# 3. OPERATIONAL AGENT METRICS
# ═══════════════════════════════════════════════════════════════

# ── Tool extraction from agent trace ─────────────────────────

def count_destructive_filter_calls(tool_chain_log: list[str]) -> int:
    """
    Hitung berapa kali reasoner memanggil filter_by_branch/_collection_type/
    _language dengan argumen yang tidak didukung pool sama sekali — tool_executor
    mendeteksi narrowing yang akan menghapus seluruh pool (lihat
    DESTRUCTIVE_FILTER_TAG di agent/nodes/tool_executor.py) dan membatalkannya,
    tapi panggilan itu sendiri tetap menandakan hallucinated/ungrounded
    reasoning dari LLM kecil (8B/7B) yang menebak atribut yang tidak disebut
    user. tool_set_match tidak bisa melihat ini karena formulanya recall-only
    (extra tools tidak pernah dihukum) — metrik ini menutup gap tersebut.
    """
    return sum(1 for entry in tool_chain_log if DESTRUCTIVE_FILTER_TAG in entry)


# Token yang muncul di tool_chain_log tapi BUKAN nama tool sungguhan — hasil
# parsing baris force-FINISH / retry reasoner (mis. "reasoner #3 → stuck-loop,
# force FINISH", "→ invalid action diulang", "→ unknown action '...'"). Tanpa
# di-skip, token ini bocor ke `tools_used` dan bikin trace seolah agent
# memanggil tool bernama "stuck"/"invalid"/"unknown".
_NON_TOOL_TOKENS = frozenset({"finish", "parse", "parse-fail", "stuck", "invalid", "unknown"})


def extract_tools_used(tool_chain_log: list[str]) -> list[str]:
    """
    Extract tool names dari tool_chain_log entries.

    AgentState.tool_chain_log berisi entries seperti:
        "reasoner #1 → books_by_author({...})"
        "reasoner #2 → filter_by_branch({...})"
        "standard_rag -> vector_tool(query)"

    Returns:
        list[str]: Tool names dalam urutan pemanggilan (duplikat tetap ada),
                   tanpa "finish", "parse-fail", atau token pseudo-status.
    """
    tools: list[str] = []
    for entry in tool_chain_log:
        # Match: "reasoner #N → tool_name" / "planned #N → tool_name(...)"
        # (planned arm = workflow_planned.py: tanpa reasoner per-step, tapi
        # mencatat step ber-format sama supaya tool-nya tetap terhitung).
        m = re.search(r"(?:reasoner|planned)\s*#?\d*\s*[→\->]+\s*([a-z_]+)", entry, re.IGNORECASE)
        if m:
            tool = m.group(1).lower()
            if tool not in _NON_TOOL_TOKENS:
                tools.append(tool)
            continue
        # Match: "standard_rag -> vector_tool"
        m2 = re.search(r"->\s*([a-z_]+)", entry, re.IGNORECASE)
        if m2:
            tool = m2.group(1).lower()
            if tool not in _NON_TOOL_TOKENS:
                tools.append(tool)
    return tools


def tool_set_match(
    tool_chain_log: list[str],
    expected_tools: list[str],
    *,
    destructive_penalty: float = 0.25,
) -> float:
    """
    Tool Set Match: mengukur apakah agent memanggil tool-tool yang
    diharapkan, tanpa mempedulikan urutan pemanggilan.

    Berbeda dari factoid QA yang mungkin mengharuskan urutan tool
    tertentu, sistem rekomendasi buku memberi kebebasan pada agent
    untuk memilih urutan tool sendiri. Yang penting adalah apakah
    *set* tool yang dipanggil mencakup tool yang diharapkan.

    Formula (recall-style, extra tools not penalized — KECUALI filter
    destruktif, lihat di bawah):
        score = |called ∩ expected| / |expected| − destructive_penalty × destructive_count

    Alasan tidak memakai Jaccard murni: agent boleh memanggil tool tambahan
    (mis. categories_by_author sebagai laporan ekstra) tanpa dihukum — ini
    justru menunjukkan reasoning yang baik. Tapi filter_by_* yang argumennya
    tidak didukung pool sama sekali (terdeteksi lewat DESTRUCTIVE_FILTER_TAG,
    lihat count_destructive_filter_calls) BUKAN "extra tool yang aman" — itu
    hallucinated reasoning yang nyaris menghapus seluruh pool kandidat
    sebelum tool_executor membatalkannya. Recall-only formula sebelumnya buta
    terhadap kegagalan ini; sekarang dihukum dengan penalty per kemunculan.

    Args:
        tool_chain_log: AgentState.tool_chain_log dari pipeline run.
        expected_tools: Ground truth field `expected_tools`.
        destructive_penalty: Pengurangan skor per destructive filter call
            (default 0.25 — heuristik, bisa ditune).

    Returns:
        float: Skor 0.0–1.0, atau -1.0 jika expected_tools kosong.

    Examples:
        >>> tool_set_match(
        ...     ["reasoner #1 → books_by_author({...})",
        ...      "reasoner #2 → filter_by_branch({...})"],
        ...     ["books_by_author", "filter_by_branch"]
        ... )
        1.0

        >>> # Extra (non-destructive) tools are not penalized:
        >>> tool_set_match(
        ...     ["reasoner #1 → categories_by_author({...})",
        ...      "reasoner #2 → books_by_author({...})",
        ...      "reasoner #3 → filter_by_branch({...})"],
        ...     ["books_by_author", "filter_by_branch"]
        ... )
        1.0

        >>> # Partial match:
        >>> tool_set_match(
        ...     ["reasoner #1 → categories_by_author({...})"],
        ...     ["books_by_author", "filter_by_branch"]
        ... )
        0.0

        >>> # Destructive filter call IS penalized, even though it's "extra":
        >>> tool_set_match(
        ...     ["reasoner #1 → books_by_author({...})",
        ...      "reasoner #2 → filter_by_branch({...})",
        ...      "tool_executor → filter_by_branch: filter_by_branch{...} → "
        ...      "0/12 buku lolos filter (filter diabaikan, pool dipertahankan)."],
        ...     ["books_by_author"]
        ... )
        0.75
    """
    if not expected_tools:
        return -1.0

    called_set = set(extract_tools_used(tool_chain_log))
    expected_set = set(t.lower() for t in expected_tools)

    if not expected_set:
        return -1.0

    intersection = called_set & expected_set
    recall = len(intersection) / len(expected_set)
    destructive = count_destructive_filter_calls(tool_chain_log)
    score = recall - destructive_penalty * destructive
    return round(max(0.0, min(1.0, score)), 4)


# ═══════════════════════════════════════════════════════════════
# CONTEXT FORMATTING HELPER
# ═══════════════════════════════════════════════════════════════

def build_contexts(state) -> list[str]:
    """
    Format konteks dari curated_context untuk RAGAS dataset builder.

    Mengonversi setiap BookNode dalam state.curated_context menjadi
    string deskriptif yang mencakup semua relasi ontologi (author,
    category, vibe, setting, branch, sinopsis).

    Args:
        state: AgentState — harus punya field `curated_context: list[BookNode]`.

    Returns:
        list[str]: Satu string per buku, siap dipakai sebagai `contexts`
                   dalam RAGAS Dataset.
    """
    contexts = []
    for book in state.curated_context:
        parts = [f"Judul: {book.title}"]
        if book.author_names:
            parts.append(f"Penulis: {', '.join(book.author_names)}")
        if book.categories:
            parts.append(f"Kategori: {', '.join(c.name for c in book.categories)}")
        if book.vibe_names:
            parts.append(f"Vibe: {', '.join(book.vibe_names)}")
        if book.setting_names:
            parts.append(f"Latar: {', '.join(book.setting_names)}")
        # Atribut yang JUGA disuntikkan ke konteks Responder (agent/nodes/responder.py
        # _build_rich_context) dan boleh dikutip di alasan rekomendasi — HARUS ikut di
        # sini agar Faithfulness dinilai terhadap konteks yang sama; kalau tidak, DDC/
        # bahasa/penerbit/tahun yang nyata malah tervonis "dikarang" (artefak).
        if getattr(book, "characters", None):
            parts.append(f"Tokoh: {', '.join(c.name for c in book.characters)}")
        if getattr(book, "ddc_class", None):
            parts.append(f"DDC: {book.ddc_class}")
        if getattr(book, "language", None):
            parts.append(f"Bahasa: {book.language}")
        if getattr(book, "publisher", None) and book.publisher.name:
            pub = book.publisher.name + (f" ({book.publisher.city})" if book.publisher.city else "")
            parts.append(f"Penerbit: {pub}")
        if getattr(book, "pub_year", None):
            parts.append(f"Terbit: {book.pub_year}")
        if book.is_available:
            parts.append(f"Tersedia di: {', '.join(book.available_at)}")
        if book.abstract_clean:
            parts.append(f"Sinopsis: {book.abstract_clean}")
        contexts.append(" | ".join(parts))
    return contexts
