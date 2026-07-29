"""
agent/core/workflow_pure_react.py — Pure Full-Autonomy ReAct (Ablation)
─────────────────────────────────────────────────────────────────────────
Arsitektur:

    query → reasoner ⇄ tool_executor → ... → FINISH (atau MAX_REACT_STEPS) → responder

Beda dari `workflow.py` (Search-Space-Gated ReAct):
  - TIDAK ADA phase expand→curate. Di SSG, setelah seed pertama pool di-prune &
    action space menyempit ke shrink-only (filter saja). Di sini action space
    FLAT & KONSTAN dari step pertama sampai terakhir: SEED + MULTIHOP +
    CURATION + COLLABORATIVE + SIMILARITY + "vector_search" (lihat
    `agent.tools.PURE_REACT_TOOLS`) — tak pernah dipersempit.
  - Responder dipanggil dengan `self_correct=False` — TIDAK ada retry LLM
    call kedua saat audit gagal.

Sama dengan SSG: tak ada router/front-door, pool mulai KOSONG, reasoner sendiri
yang mengisi — `vector_search` adalah tool biasa yang dipilih reasoner (lewat
`tool_executor_node`'s VECTOR_TOOLS branch) di KEDUA arm.

Tujuan: ablation arm buat dibandingkan ke Search-Space-Gated ReAct, mengetes
hipotesis "action space yang nggak flat/konsisten itu beban kognitif buat
model kecil" — lihat docs/catatan_riset.md.

Public API: `run_workflow_pure_react(query: str) -> AgentState`. Skema
AgentState yang dikembalikan identik dengan `run_workflow()`, sehingga
bisa dievaluasi dengan harness yang sama (evaluation/run_comparative_evaluation.py).
"""

from __future__ import annotations

import logging

from agent.core.state import AgentState, recommendation_order, RECOMMEND_TOP_K
from agent.nodes.reasoner import _PURE_REACT_PROMPT, reasoner_node
from agent.nodes.responder import responder_node
from agent.nodes.tool_executor import tool_executor_node
from agent.tools import PURE_REACT_TOOLS

logger = logging.getLogger(__name__)

# Same ceiling as workflow.py — fair comparison needs the same step budget.
MAX_REACT_STEPS = 4


def run_workflow_pure_react(query: str) -> AgentState:
    """
    Jalankan pure full-autonomy ReAct workflow end-to-end (ablation arm).

    Loop: reasoner ⇄ tool_executor → ... → reasoner FINISH → responder
    (tanpa self-correct).
    """
    state = AgentState(query=query, route="pure_react", phase="react")
    allowed_tools = list(PURE_REACT_TOOLS)

    for _ in range(MAX_REACT_STEPS):
        logger.info("=== Pure-ReAct step %d/%d ===", state.react_step + 1, MAX_REACT_STEPS)

        state = reasoner_node(state, tool_names=allowed_tools, base_prompt=_PURE_REACT_PROMPT)
        if state.error:
            logger.error("Reasoner error: %s", state.error)
            return state

        if state.is_finished:
            logger.info("Reasoner memutuskan FINISH di step %d.", state.react_step)
            break

        # Reasoner kadang menulis observation tanpa tool call (mis. action invalid).
        if not state.next_action:
            logger.info("Reasoner step %d tidak menghasilkan tool call — lanjut ke step berikut.", state.react_step)
            continue

        state = tool_executor_node(state)
        if state.error:
            logger.error("Tool executor error: %s", state.error)
            return state
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
                    f"workflow_pure_react → max steps, force-curated top {len(curated)} from pool"
                ],
            })

    # ── Responder (synthesis + audit, TANPA self-correct) ────────────────
    logger.info("=== Responder (self_correct=False) ===")
    state = responder_node(state, self_correct=False)

    if state.is_hallucinating:
        logger.warning(
            "Pure-ReAct workflow selesai dengan %d violations (self-correct off).",
            len(state.violations),
        )
    else:
        logger.info("Pure-ReAct workflow selesai bersih.")

    return state
