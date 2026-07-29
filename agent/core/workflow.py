"""
agent/core/workflow.py — Search-Space-Gated ReAct Workflow Orchestrator (v2)
───────────────────────────────────────────────────────────────────────────
Arsitektur (v2 — gating pindah dari ACTION space ke SEARCH space):

    query → phase="expand": reasoner memilih SATU retrieval paling presisi
              dari MENU PENUH (seed / kombinasi multi-atribut / collaborative /
              vector_search) untuk membentuk pool awal
              │
              └─ setelah satu ekspansi non-kosong → prune pool ke top-K →
                 phase="curate": action space dipersempit ke SHRINK-ONLY
                 (filter_by_* + categories_by_author) — pool hanya boleh
                 MENGECIL, tidak boleh tumbuh lagi

    FINISH (atau MAX_REACT_STEPS) → responder (synthesis + audit)

Kenapa berubah dari v1 (vector-gated lama): v1 mempersempit ACTION space
(route "vector" → cuma boleh filter, MULTIHOP/COLLABORATIVE di-exclude),
sehingga query multi-hop bervibe/setting tak pernah bisa memanggil combo tool
yang mereka butuhkan (`books_by_vibe_and_setting_and_category`, dst.) → P@K &
TSM ambruk di multi-hop (lihat docs/hasil.md § breakdown hop_count). v2
mempertahankan tujuan asli — *mempersempit SEARCH space* demi latency rendah &
jawaban grounded — tapi lewat mekanisme yang benar: (1) reasoner bebas memilih
retrieval presisi apa pun untuk seed (tak ada router yang menutup akses tool),
(2) pool di-cap ke top-K (prune) supaya prompt kecil, (3) setelah seed, action
space shrink-only supaya search space tak meledak. Grounding tetap dijaga
responder audit, bukan oleh pembatasan tool.

Public API tetap kompatibel: `run_workflow(query: str) -> AgentState`.
"""

from __future__ import annotations

import logging

from agent.core.state import AgentState, recommendation_order, RECOMMEND_TOP_K
from agent.nodes.reasoner import _CURATE_PROMPT, _PURE_REACT_PROMPT, reasoner_node
from agent.nodes.responder import responder_node
from agent.nodes.tool_executor import tool_executor_node
from agent.tools import COLLABORATIVE_TOOLS, CURATION_TOOLS, MULTIHOP_TOOLS, SEED_TOOLS

logger = logging.getLogger(__name__)


# Safety ceilings ------------------------------------------------------------
MAX_REACT_STEPS = 4          # sama dengan arm lain — fair comparison

# Pool di-cap ke top-K setelah seed: prompt reasoner/synthesis tetap kecil
# (latency) & grounding lebih ketat, tanpa membatasi action space.
_POOL_PRUNE_TOP_K = 12

# Fase "expand": menu retrieval PENUH — reasoner memilih primitif penyempit
# paling presisi untuk query (seed atribut tunggal / kombinasi multi-atribut /
# collaborative "mirip X" / vector semantik). TIDAK di-gate oleh frasa query
# (tak ada router): search space dibatasi belakangan oleh fase curate yang
# shrink-only + prune, bukan oleh pembatasan tool retrieval mana yang boleh.
EXPAND_TOOLS = list(SEED_TOOLS) + list(MULTIHOP_TOOLS) + list(COLLABORATIVE_TOOLS) + ["vector_search"]

# Fase "curate": shrink-only — pool hanya boleh mengecil (filter) atau
# dilaporkan (categories_by_author), tidak boleh tumbuh lagi.
CURATE_TOOLS = list(CURATION_TOOLS)


def _prune_pool(state: AgentState) -> AgentState:
    """Cap working pool ke top-K paling relevan (tersedia dulu) supaya search
    space tetap sempit — prompt reasoner/synthesis kecil (latency) & grounding
    lebih ketat, TANPA menyentuh action space."""
    if len(state.enriched_data) <= _POOL_PRUNE_TOP_K:
        return state
    pruned = sorted(
        state.enriched_data,
        key=lambda b: (not b.is_available, -b.relevance_score),
    )[:_POOL_PRUNE_TOP_K]
    return state.model_copy(update={
        "enriched_data": pruned,
        "tool_chain_log": state.tool_chain_log + [
            f"workflow → prune pool → top {_POOL_PRUNE_TOP_K}"
        ],
    })


def run_workflow(query: str) -> AgentState:
    """
    Jalankan Search-Space-Gated ReAct workflow end-to-end.

    Loop: reasoner ⇄ tool_executor (expand→curate) → FINISH → responder.
    """
    state = AgentState(query=query, route="search_space_gated", phase="expand")
    allowed_tools = EXPAND_TOOLS
    base_prompt = _PURE_REACT_PROMPT

    # ── ReAct loop (reasoner ⇄ tool_executor) ────────────────────────────
    for _ in range(MAX_REACT_STEPS):
        logger.info(
            "=== ReAct step %d/%d (phase=%s) ===",
            state.react_step + 1, MAX_REACT_STEPS, state.phase,
        )

        # Expand: framing full-autonomy (aturan pemilihan entry-point — combo
        # untuk multi-atribut, collaborative untuk "mirip X"). Curate: prompt
        # shrink-only khusus supaya model tidak buang step mencoba tool
        # retrieval yang sudah diblok (itu yang meledakkan latency di v2 awal).
        state = reasoner_node(state, tool_names=allowed_tools, base_prompt=base_prompt)
        if state.error:
            logger.error("Reasoner error: %s", state.error)
            return state

        if state.is_finished:
            logger.info("Reasoner memutuskan FINISH di step %d.", state.react_step)
            break

        # Reasoner kadang menulis observation tanpa tool call (mis. action invalid).
        if not state.next_action:
            logger.info("Reasoner step %d tidak menghasilkan tool call — lanjut.", state.react_step)
            continue

        state = tool_executor_node(state)
        if state.error:
            logger.error("Tool executor error: %s", state.error)
            return state

        # Kunci search space setelah ekspansi PERTAMA yang non-kosong: prune,
        # lalu izinkan hanya curation shrink-only untuk sisa loop. Kalau seed
        # balik kosong, TETAP di expand supaya reasoner boleh coba primitif
        # retrieval lain, bukan mengkurasi pool kosong.
        if state.phase == "expand" and state.enriched_data:
            state = _prune_pool(state)
            state = state.model_copy(update={"phase": "curate"})
            allowed_tools = CURATE_TOOLS
            base_prompt = _CURATE_PROMPT
    else:
        # Loop habis tanpa FINISH — paksa responder dengan apa yang ada
        logger.warning(
            "Max ReAct steps (%d) tercapai tanpa FINISH. Memaksa responder dengan pool saat ini.",
            MAX_REACT_STEPS,
        )
        if not state.curated_context and state.enriched_data:
            curated = recommendation_order(state.enriched_data)[:RECOMMEND_TOP_K]
            state = state.model_copy(update={
                "curated_context": curated,
                "is_finished":     True,
                "tool_chain_log":  state.tool_chain_log + [
                    f"workflow → max steps, force-curated top {len(curated)} from pool"
                ],
            })

    # ── Responder (synthesis + audit deterministik, TANPA self-correct) ──
    # self_correct=False: A/B terkontrol (catatan_riset.md § 4.1) menunjukkan
    # LLM retry self-correct itu net-negatif — AC turun & latency naik 15-35%
    # tanpa gain faithfulness konsisten. Grounding cukup dari retrieval presisi
    # + pool kecil-prune. Audit deterministik (_run_audit) TETAP jalan buat
    # observability; env DISABLE_SELF_CORRECT juga masih bisa override.
    logger.info("=== Responder ===")
    state = responder_node(state, self_correct=False)

    if state.is_hallucinating:
        logger.warning(
            "Workflow selesai dengan %d violations yang bertahan.",
            len(state.violations),
        )
    else:
        logger.info("Workflow ✅ selesai bersih.")

    return state
