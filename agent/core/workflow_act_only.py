"""
agent/core/workflow_act_only.py — Act-Only ReAct (Ablation)
─────────────────────────────────────────────────────────────
Arsitektur:

    query → reasoner ⇄ tool_executor → ... → FINISH (atau MAX_REACT_STEPS) → responder

Beda dari `workflow_pure_react.py` HANYA satu hal: prompt reasoner
(`_ACT_ONLY_PROMPT`) tidak punya field "thought" — model dilarang menulis
penalaran, langsung memilih action. Segalanya yang lain identik: action
space flat yang sama (PURE_REACT_TOOLS), MAX_REACT_STEPS sama, loop-guard
sama, responder tanpa self-correct.

Ini baseline "Act" dari grid ablasi paper ReAct (Yao et al.): CoT-RAG
(reason-only, standard_rag.py cot=True) vs Act-only (act-only, file ini)
vs ReAct (keduanya, workflow_pure_react.py). Selisih metrik pure_react −
act_only = kontribusi interleaved CoT di dalam loop; lihat
docs/catatan_riset.md.

Catatan implementasi: reasoner_node mentolerir absennya "thought"
(default string kosong), jadi tidak ada perubahan parsing yang diperlukan —
scratchpad tetap merender baris "Thought n:" kosong, dan reasoning_log
berisi entri kosong. Itu disengaja: harness benar-benar identik antar arm,
satu-satunya variabel adalah channel reasoning di prompt.

Public API: `run_workflow_act_only(query: str) -> AgentState`. Skema
AgentState identik dengan `run_workflow()`/`run_workflow_pure_react()`,
sehingga dievaluasi dengan harness yang sama
(evaluation/run_comparative_evaluation.py).
"""

from __future__ import annotations

import logging

from agent.core.state import AgentState, recommendation_order, RECOMMEND_TOP_K
from agent.nodes.reasoner import _ACT_ONLY_PROMPT, reasoner_node
from agent.nodes.responder import responder_node
from agent.nodes.tool_executor import tool_executor_node
from agent.tools import PURE_REACT_TOOLS

logger = logging.getLogger(__name__)

# Same ceiling as workflow.py / workflow_pure_react.py — fair comparison
# needs the same step budget.
MAX_REACT_STEPS = 4


def run_workflow_act_only(query: str) -> AgentState:
    """
    Jalankan Act-only ReAct workflow end-to-end (ablation arm).

    Loop: reasoner (tanpa thought) ⇄ tool_executor → ... → FINISH → responder
    (tanpa self-correct).
    """
    state = AgentState(query=query, route="act_only", phase="react")
    allowed_tools = list(PURE_REACT_TOOLS)

    for _ in range(MAX_REACT_STEPS):
        logger.info("=== Act-only step %d/%d ===", state.react_step + 1, MAX_REACT_STEPS)

        state = reasoner_node(state, tool_names=allowed_tools, base_prompt=_ACT_ONLY_PROMPT)
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
                    f"workflow_act_only → max steps, force-curated top {len(curated)} from pool"
                ],
            })

    # ── Responder (synthesis + audit, TANPA self-correct) ────────────────
    logger.info("=== Responder (self_correct=False) ===")
    state = responder_node(state, self_correct=False)

    if state.is_hallucinating:
        logger.warning(
            "Act-only workflow selesai dengan %d violations (self-correct off).",
            len(state.violations),
        )
    else:
        logger.info("Act-only workflow selesai bersih.")

    return state
