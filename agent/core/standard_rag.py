"""
agent/core/standard_rag.py — Standard RAG & CoT-RAG Baselines
────────────────────────────────────────────────────────────────
Dua baseline non-agentic (tanpa ReAct loop), keduanya Retrieve → Generate
dengan retrieval yang IDENTIK (single-hop vector search, top_k sama):

  - run_standard_rag()     : generate langsung (tanpa reasoning eksplisit).
  - run_standard_rag_cot() : generate dengan chain-of-thought — model
    menalar langkah-demi-langkah atas konteks dulu, lalu menutup dengan
    marker "JAWABAN AKHIR:". Hanya teks SETELAH marker yang masuk
    state.final_answer (yang dinilai answer_contains/RAGAS); penalaran
    lengkap disimpan di state.assembly_draft + reasoning_log untuk inspeksi.

Karena retrieval-nya sama persis, precision@K kedua arm identik by
construction — selisih skor generation murni efek reasoning. Ini arm "CoT"
(reason-only, tanpa acting) dalam grid ablasi ala paper ReAct:
CoT-RAG vs Act-only (workflow_act_only.py) vs ReAct (workflow_pure_react.py).
"""

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agent.core.state import AgentState, RECOMMEND_TOP_K
from agent.tools.vector_tool import VectorSearchTool
from agent.services.llm_services import get_llm

logger = logging.getLogger(__name__)

# System prompt untuk baseline RAG
_SYSTEM_PROMPT = """Anda adalah asisten perpustakaan.
Tugas Anda adalah menjawab pertanyaan pengguna HANYA berdasarkan konteks yang diberikan.
Jika Anda tidak mengetahui jawabannya dari konteks, katakan bahwa Anda tidak tahu.
Usahakan jawaban singkat dan relevan. Jangan mengarang informasi.
"""

# System prompt untuk arm CoT-RAG — sama grounding rule-nya, plus instruksi
# reasoning eksplisit dan marker pemisah jawaban final.
_COT_SYSTEM_PROMPT = """Anda adalah asisten perpustakaan.
Tugas Anda adalah menjawab pertanyaan pengguna HANYA berdasarkan konteks yang diberikan.

Sebelum menjawab, PIKIRKAN LANGKAH DEMI LANGKAH:
1. Identifikasi apa saja yang diminta pengguna (tema/vibe, penulis, kategori,
   cabang perpustakaan, dll.).
2. Periksa buku-buku pada konteks SATU PER SATU: cocok atau tidak dengan
   setiap kriteria permintaan, dan mengapa.
3. Simpulkan buku mana yang paling relevan berdasarkan pemeriksaan tersebut.

Tuliskan penalaran Anda terlebih dahulu, lalu tutup dengan jawaban final
setelah baris penanda PERSIS berikut (wajib ada, tepat satu kali):

JAWABAN AKHIR:

Semua teks setelah "JAWABAN AKHIR:" adalah jawaban yang dibaca pengguna —
singkat, relevan, dan HANYA berdasarkan konteks. Jika jawabannya tidak ada
di konteks, katakan bahwa Anda tidak tahu. Jangan mengarang informasi.
"""

# Cap token output khusus CoT: reasoning + jawaban tidak muat di default 700
# (get_llm _DEFAULT_NUM_PREDICT) — kalau terpotong sebelum marker muncul,
# jawaban final ikut hilang. Konsekuensinya latency arm ini lebih tinggi;
# itu bagian dari trade-off yang memang mau diukur, bukan disembunyikan.
_COT_NUM_PREDICT = 1400

_ANSWER_MARKER = re.compile(r"JAWABAN\s+AKHIR\s*:", re.IGNORECASE)


def _split_cot_answer(raw: str) -> tuple[str, str]:
    """
    Pisahkan (reasoning, final_answer) pada marker "JAWABAN AKHIR:".
    Kalau model menyebut marker lebih dari sekali, ambil teks setelah
    kemunculan TERAKHIR sebagai jawaban. Marker absen → ("", "").
    """
    parts = _ANSWER_MARKER.split(raw)
    if len(parts) < 2:
        return "", ""
    return parts[0].strip(), parts[-1].strip()


def run_standard_rag(query: str, top_k: int = RECOMMEND_TOP_K, cot: bool = False) -> AgentState:
    """
    Jalankan Standard RAG pipeline (Retrieve -> Generate).
    Mengembalikan format AgentState yang sama dengan workflow agentic.

    cot=True mengaktifkan varian CoT-RAG: retrieval identik, tapi generation
    memakai _COT_SYSTEM_PROMPT (reasoning eksplisit + marker "JAWABAN AKHIR:")
    dan cap token yang lebih longgar.
    """
    label = "standard_rag_cot" if cot else "standard_rag"
    state = AgentState(query=query, intent=label, entry_point=label)

    logger.info("%s: Mencari konteks via VectorSearchTool...", label)
    vector_tool = VectorSearchTool()

    # 1. RETRIEVE
    curated_context = vector_tool.search(query=query, top_k=top_k, diversify_by_title=True)
    state.curated_context = curated_context
    state.tool_chain_log.append(f"{label} -> vector_tool(query)")

    # 2. FORMAT CONTEXT
    context_str = ""
    if not curated_context:
        context_str = "Tidak ada buku yang relevan ditemukan di database."
    else:
        for idx, book in enumerate(curated_context, 1):
            context_str += f"\n--- Buku {idx} ---\n"
            context_str += f"ID: {book.book_id}\n"
            context_str += f"Judul: {book.title}\n"
            context_str += f"Penulis: {', '.join(book.author_names) if book.author_names else 'Unknown'}\n"
            context_str += f"Kategori: {', '.join([c.name for c in book.categories]) if book.categories else 'Unknown'}\n"
            context_str += f"Vibe: {', '.join(book.vibe_names) if book.vibe_names else 'Unknown'}\n"
            context_str += f"Latar: {', '.join(book.setting_names) if book.setting_names else 'Unknown'}\n"
            context_str += f"Stok: {', '.join(book.available_at) if book.is_available else 'Tidak Tersedia'}\n"
            context_str += f"Sinopsis: {book.abstract_clean}\n"

    # 3. GENERATE
    llm = get_llm(num_predict=_COT_NUM_PREDICT) if cot else get_llm()
    system_prompt = _COT_SYSTEM_PROMPT if cot else _SYSTEM_PROMPT

    user_prompt = f"""Konteks Buku:
{context_str}

Pertanyaan Pengguna:
{query}
"""

    logger.info("%s: Menghasilkan jawaban...", label)
    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = llm.invoke(messages)
        raw_answer = response.content if isinstance(response.content, str) else str(response.content)
        state.token_usage = state.token_usage.add(response)

        if cot:
            reasoning, answer = _split_cot_answer(raw_answer)
            state.assembly_draft = raw_answer  # trace CoT lengkap, untuk inspeksi
            if reasoning:
                state.reasoning_log.append(reasoning)
            if not answer:
                # Marker tidak muncul (atau output terpotong tepat di marker) —
                # fallback ke teks penuh supaya jawaban tidak kosong, tapi
                # tandai supaya kelihatan saat analisis hasil.
                state.fallback_reason = "cot_marker_missing"
                answer = raw_answer.strip()
            state.final_answer = answer
        else:
            state.final_answer = raw_answer

        state.is_finished = True

    except Exception as e:
        logger.error(f"{label} error saat generasi: {e}")
        state.error = str(e)
        state.final_answer = "Maaf, terjadi kesalahan saat menghasilkan jawaban."

    return state


def run_standard_rag_cot(query: str, top_k: int = RECOMMEND_TOP_K) -> AgentState:
    """CoT-RAG arm — wrapper agar bisa dipakai langsung sebagai pipeline_func."""
    return run_standard_rag(query, top_k=top_k, cot=True)
