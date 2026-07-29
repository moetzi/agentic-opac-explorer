"""
agent/core/workflow_planned.py — Single-Shot Planned Retrieval (Ablation)
─────────────────────────────────────────────────────────────────────────
Arsitektur:

    query → planner (SATU LLM call: rencanakan seluruh urutan tool + args
              dari menu penuh) → eksekusi deterministik tiap step (TANPA LLM
              di antaranya) → curate top-K → responder (synthesis + audit)

Beda dari `workflow.py` (Search-Space-Gated ReAct) & `workflow_pure_react.py`:
  - TIDAK ADA loop ReAct. Reasoner tidak dipanggil per-step. Seluruh rencana
    retrieval diputuskan dalam SATU LLM call di depan, lalu dieksekusi apa
    adanya. Ini menguji hipotesis: "apakah loop reason⇄act per-step memang
    perlu, atau retrieval bisa direncanakan sekali di awal?"
  - Latency: 2 LLM call (plan + synthesis) vs 4-step ReAct — sumber utama
    latency (jumlah inferensi reasoner) dipangkas, action space TETAP penuh
    (planner lihat semua tool).
  - Grounding dijaga audit deterministik responder, TANPA self-correct
    (`self_correct=False`, lihat pemanggilan di bawah): retry LLM-nya terbukti
    net-negatif di A/B audit on/off (catatan_riset.md § 4.1) — AC turun, latency
    +15-35%, faithfulness ±0.02 — jadi Planned sengaja mematikannya.

Menu tool = `agent.tools.PURE_REACT_TOOLS` (seed + multihop + collaborative +
curation + vector_search) — planner boleh menyusun seed retrieval + filter
lanjutan dalam satu rencana.

Public API: `run_workflow_planned(query: str) -> AgentState` — skema
AgentState identik dengan `run_workflow()`, bisa dievaluasi harness yang sama.
"""

from __future__ import annotations

import json
import logging

from agent.core.state import AgentState, ReActStep, recommendation_order, RECOMMEND_TOP_K
from agent.nodes.reasoner import _extract_json
from agent.nodes.responder import responder_node
from agent.nodes.tool_executor import tool_executor_node
from agent.services.llm_services import llm_json
from agent.tools import PURE_REACT_TOOLS, build_specs_prompt
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# Batas panjang rencana — cukup untuk 1 seed retrieval + 1-2 filter lanjutan;
# menahan planner meledakkan search space dengan banyak ekspansi.
_MAX_PLAN_STEPS = 3
# Jumlah judul final = konstanta bersama (state.RECOMMEND_TOP_K) agar seragam
# lintas keenam pipeline; juga jadi ambang cukup-kandidat untuk hentikan fallback.
_CURATE_TOP_K = RECOMMEND_TOP_K

# ── Fallback fuzzy (advisor-requested safety net) ────────────────────────────
# Vibe/Setting/Character adalah node HASIL EKSTRAKSI LLM dari sinopsis; kualitas
# sinopsis buruk & tak semua buku punya sinopsis, jadi retrieval berbasis atribut
# itu rapuh (pool kosong/sangat sedikit untuk buku tanpa sinopsis yang layak).
# Ketika rencana bertumpu pada atribut rapuh ini DAN pool hasilnya di bawah
# ambang, jatuhkan ke fuzzy-match terhadap field katalog yang RELIABLE — judul
# atau kategori mentah — lewat `books_by_title_or_category_fuzzy`.
_FALLBACK_MIN_POOL = 3
# Arg-key yang nilainya berasal dari ekstraksi sinopsis (memicu fallback).
_FRAGILE_ARG_KEYS = ("vibe", "setting", "character")
# Tool yang bertumpu pada atribut/sinopsis rapuh (vibe-share / embedding-KNN).
_FRAGILE_TOOLS = frozenset({
    "books_sharing_vibe_with", "books_sharing_vibe_with_setting", "search_similar_runtime",
})
# Arg-key yang boleh dipakai sebagai keyword fuzzy (atribut tematik + kategori).
# 'title' sengaja TIDAK dipakai: mem-fuzzy judul referensi ke judul buku lain
# tak menghasilkan "buku serupa".
_FUZZY_KEYWORD_KEYS = ("setting", "vibe", "character", "category")
_MAX_FALLBACK_KEYWORDS = 2


_PLANNER_PROMPT = """You are a retrieval PLANNER for a library book recommendation
system. In ONE shot, plan the FULL ordered sequence of tool calls needed to
answer the user's query. Your plan will be executed EXACTLY as written, with NO
further reasoning between steps — so decide everything now.

Book titles, author names, vibes, settings, and user queries are in Bahasa
Indonesia (Jakarta Public Library catalog) — extract entity values as-is, do
NOT translate them.

Neo4j Knowledge Graph ontology (11 traversable entities around :Book):

  (:Author)-[:WROTE]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                            ↓
                   [:BELONGS_TO]->(:Category)
                   [:AVAILABLE_AT]->(:Branch)
                   [:CLASSIFIED_AS]->(:DDCClass)
                   [:WRITTEN_IN]->(:Language)
                   [:COLLECTION_TYPE]->(:CollectionType)
                   [:HAS_VIBE]->(:Vibe)
                   [:HAS_SETTING]->(:Setting)
                   [:FEATURES_CHARACTER]->(:Character)

ENTITY -> SEED TOOL MAP — EVERY entity above has a retrieval path; do NOT default
to only vibe/setting/category. Pick the tool whose attribute the query actually
names (these are the single-attribute seeds; combine them per Principle 2 when the
query names several attributes):
  author            -> books_by_author(author)
  publisher         -> books_by_publisher(publisher)
  publisher's city  -> books_by_publisher_city(city)
  category          -> books_by_category(category)
  language          -> books_by_language(language)
  branch (cabang)   -> books_by_branch(branch)
  DDC classification-> books_by_ddc(ddc_prefix)
  collection type   -> books_by_collection_type(collection_type)
  vibe / nuansa     -> books_by_vibe(vibe)
  setting / latar   -> books_by_setting(setting)
  character / tokoh -> books_by_character(character)
  a specific title  -> lookup_by_title(title)

PLANNING PRINCIPLES:
1. STEP 1 MUST populate the candidate pool (a retrieval tool), never a filter.
   Pick the RIGHT entry point:
   - Thematic/abstract (vibe, mood) with no concrete attribute -> `vector_search`.
   - A concrete attribute (author, category, DDC, language, branch, title) ->
     the matching `books_by_*` tool.
   - "buku yang MIRIP/SERUPA/SETEMA dengan <Judul>" (generic similarity, no
     attribute named) -> `search_similar_runtime` with the reference title —
     NOT vector_search, NOT books_sharing_vibe_with.
   - "buku lain dengan VIBE/NUANSA yang SAMA dengan <Judul>" -> `books_sharing_vibe_with`.
     "buku lain dengan DDC/KLASIFIKASI yang SAMA dengan <Judul>" ->
     `books_sharing_ddc_with`. (Only when the shared attribute is named explicitly.)
   - vibe/category + branch ("buku [vibe] di [cabang]") -> `books_by_vibe_and_branch`
     / `books_by_category_and_branch` directly (NOT vector_search + filter).
2. MATCH THE TOOL TO EXACTLY THE ATTRIBUTES PRESENT — do not add a vibe, setting,
   or category the user did not state. Over-specifying (using a 3-attribute tool
   when only 2 attributes were named) invents a phantom constraint and returns
   the WRONG books. Pick the tightest tool that covers ONLY the stated attributes:
   - setting only ("buku berlatar [X]")                 -> `books_by_setting`
   - vibe only ("buku bernuansa [X]")                   -> `books_by_vibe`
   - setting + category ("[kategori] berlatar [X]")     -> `books_by_setting_and_category`
   - vibe + setting ("buku [vibe] berlatar [X]")        -> `books_by_vibe_and_setting`
   - vibe + category ("[kategori] bernuansa [vibe]")    -> `books_by_vibe_and_category`
   - vibe + setting + category (ALL THREE named)        -> `books_by_vibe_and_setting_and_category`
   Use the 3-attribute composite ONLY when the query names a vibe AND a setting
   AND a category — never to fill an unstated slot.
3. GENERIC FILLER WORDS ARE NOT A CATEGORY. Words like "novel", "buku", "cerita",
   "bacaan", "karya" are filler and MUST NOT become a `category` argument. Only a
   SPECIFIC named category counts (e.g. "Cerita Anak", "Dongeng", "Komik",
   "Fiksi Indonesia", "Fiksi Inggris", "Islam"). So "novel berlatar kerajaan" has
   ONLY a setting -> `books_by_setting`, not a setting+category tool.
3b. GENRE/MOOD WORDS ARE VIBES, NOT CATEGORIES. "romance", "misteri", "thriller",
   "komedi", "sejarah", "fantasi", "horor", "petualangan", "biografi", "religius",
   "keluarga", "inspiratif", "motivasi", "drama" are HAS_VIBE values in this KG —
   pass them as `vibe`, never `category`. So "buku komedi di [cabang]" ->
   `books_by_vibe_and_branch` (vibe="komedi"), and "buku sejarah di [cabang]" ->
   `books_by_vibe_and_branch` (vibe="sejarah"), NOT books_by_category_and_branch.
4. THEN add filter step(s) ONLY for attributes the seed tool did not already
   apply: `filter_by_branch`, `filter_by_collection_type`, `filter_by_language`,
   `filter_by_author`. Use a filter ONLY when NO combined tool covers the pair:
   - Author+branch (no combo) -> books_by_author THEN filter_by_branch.
   - Character+author (no combo) -> books_by_character THEN filter_by_author.
   - Author+category HAS a combined tool -> use `books_by_author_and_category`
     (do NOT decompose it; there is no filter_by_category).
5. Use real entity names in args, NEVER internal IDs. Derive every arg from the
   query — do NOT hallucinate attributes the user did not mention.
6. Keep the plan MINIMAL (1-3 steps). If one seed tool fully answers the query,
   the plan is just that one step.
7. Use ONLY tools from the list below, with EXACT names. Do NOT invent
   `filter_by_vibe` / `filter_by_category` — for vibe/setting/category use the
   `books_by_*` retrieval tools, not a filter.

AVAILABLE TOOLS (grouped under [HEADERS] for clarity only — headers are not
literal syntax, pick any tool from any group):
{tool_specs}

OUTPUT FORMAT — a SINGLE JSON object ONLY, no prose, no markdown fence:

{{
  "plan": [
    {{"tool": "books_by_vibe_and_setting_and_category", "action_input": {{"vibe": "keluarga", "setting": "rumah", "category": "Cerita Anak"}}}},
    {{"tool": "filter_by_branch", "action_input": {{"branch": "Cikini"}}}}
  ]
}}

EXAMPLES:
- "Novel bertema petualangan berlatar perkotaan" (vibe + setting; "Novel" = filler) ->
  {{"plan": [{{"tool": "books_by_vibe_and_setting", "action_input": {{"vibe": "petualangan", "setting": "perkotaan"}}}}]}}
- "Cerita Anak bernuansa petualangan berlatar hutan" (vibe + setting + REAL category) ->
  {{"plan": [{{"tool": "books_by_vibe_and_setting_and_category", "action_input": {{"vibe": "petualangan", "setting": "hutan", "category": "Cerita Anak"}}}}]}}
- "Cari novel yang berlatar di perguruan tinggi" (setting only; "novel" = filler) ->
  {{"plan": [{{"tool": "books_by_setting", "action_input": {{"setting": "perguruan tinggi"}}}}]}}
- "Cari buku kategori Dongeng yang berlatar kerajaan" (setting + REAL category, NO vibe) ->
  {{"plan": [{{"tool": "books_by_setting_and_category", "action_input": {{"setting": "kerajaan", "category": "Dongeng"}}}}]}}
- "Carikan buku yang mirip dengan \\"<Judul>\\"" (generic similarity) ->
  {{"plan": [{{"tool": "search_similar_runtime", "action_input": {{"title": "<Judul>"}}}}]}}
- "Ada buku lain dengan klasifikasi DDC yang sama dengan <Judul>?" ->
  {{"plan": [{{"tool": "books_sharing_ddc_with", "action_input": {{"title": "<Judul>"}}}}]}}
- "Buku karya Tere Liye yang ada di Perpustakaan Cikini" ->
  {{"plan": [{{"tool": "books_by_author", "action_input": {{"author": "Tere Liye"}}}}, {{"tool": "filter_by_branch", "action_input": {{"branch": "Cikini"}}}}]}}
- "Ada buku kategori Islam karya Fiedha Hasiem?" (author + REAL category) ->
  {{"plan": [{{"tool": "books_by_author_and_category", "action_input": {{"author": "Fiedha Hasiem", "category": "Islam"}}}}]}}
- "Rekomendasi buku bernuansa sendu tentang kehilangan" ->
  {{"plan": [{{"tool": "vector_search", "action_input": {{"query": "buku bernuansa sendu tentang kehilangan"}}}}]}}"""


_PLANNER_USER = """Permintaan pengguna:
"{query}"

Susun rencana retrieval (JSON) sekarang. Output HANYA satu objek JSON valid."""


def _plan(state: AgentState) -> tuple[list[dict], AgentState]:
    """Satu LLM call → rencana urutan tool. Kembalikan (plan, state) dengan
    token_usage sudah diakumulasi. Gagal parse → rencana kosong (responder
    akan melaporkan tidak ada hasil)."""
    system = _PLANNER_PROMPT.format(tool_specs=build_specs_prompt(list(PURE_REACT_TOOLS)))
    user = _PLANNER_USER.format(query=state.query)
    try:
        response = llm_json.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        raw = getattr(response, "content", "") or ""
        state = state.model_copy(update={"token_usage": state.token_usage.add(response)})
        decision = _extract_json(raw)
    except Exception as exc:
        logger.warning("Planner parse-fail: %s — rencana kosong.", exc)
        return [], state.model_copy(update={
            "tool_chain_log": state.tool_chain_log + [f"planner → parse-fail ({exc}), rencana kosong"],
        })

    plan = decision.get("plan")
    if not isinstance(plan, list):
        plan = []
    steps: list[dict] = []
    for item in plan[:_MAX_PLAN_STEPS]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        args = item.get("action_input") or item.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        if tool:
            steps.append({"tool": tool, "args": args})

    state = state.model_copy(update={
        "tool_chain_log": state.tool_chain_log + [
            "planner → " + " ; ".join(f"{s['tool']}({s['args']})" for s in steps) if steps
            else "planner → rencana kosong"
        ],
    })
    return steps, state


def _execute_step(state: AgentState, tool: str, args: dict, idx: int) -> AgentState:
    """Eksekusi satu step rencana lewat tool_executor_node (reuse merge/narrow
    semantics yang sama dengan arm lain)."""
    step = ReActStep(step=idx, thought="(planned — no per-step reasoning)",
                     action=tool, action_input=args, observation="")
    state = state.model_copy(update={
        "scratchpad":  state.scratchpad + [step],
        "next_action": {"tool": tool, "args": args},
        "react_step":  idx,
        # Entry ber-format "planned #N → tool(args)" supaya
        # evaluation/metrics.py::extract_tools_used (yang match "reasoner|planned
        # #N → tool") menangkapnya — tanpa ini tool_set_match planned = 0 palsu.
        "tool_chain_log": state.tool_chain_log + [f"planned #{idx} → {tool}({args})"],
    })
    return tool_executor_node(state)


def _needs_fallback(plan: list[dict], pool_size: int) -> bool:
    """True kalau retrieval terstruktur bertumpu pada atribut rapuh (vibe/
    setting/character/embedding) TAPI pool-nya terlalu sedikit — atau kalau
    planning gagal total (rencana kosong). Query yang murni bersandar pada
    field katalog reliable (author/branch/ddc/publisher/language) TIDAK memicu
    fallback: kalau itu sepi, memang datanya yang sedikit, bukan ekstraksi
    sinopsis yang meleset."""
    if pool_size >= _FALLBACK_MIN_POOL:
        return False
    if not plan:
        return True
    for step in plan:
        args = step.get("args") or {}
        if any(k in args for k in _FRAGILE_ARG_KEYS):
            return True
        if step.get("tool") in _FRAGILE_TOOLS:
            return True
    return False


def _fallback_keywords(plan: list[dict], query: str) -> list[str]:
    """Kumpulkan keyword tematik (nilai setting/vibe/character/category) dari
    rencana untuk di-fuzzy-match ke judul/kategori. Kalau tak ada (mis. rencana
    kosong atau hanya berisi judul referensi), pakai query utuh sebagai
    jaring terakhir. Dedupe case-insensitive, urutan dipertahankan."""
    kws: list[str] = []
    for step in plan:
        args = step.get("args") or {}
        for key in _FUZZY_KEYWORD_KEYS:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                kws.append(val.strip())
    seen: set[str] = set()
    out: list[str] = []
    for kw in kws:
        low = kw.lower()
        if low not in seen:
            seen.add(low)
            out.append(kw)
    if not out and query.strip():
        out = [query.strip()]
    return out


def run_workflow_planned(query: str) -> AgentState:
    """Jalankan single-shot planned-retrieval workflow end-to-end (ablation arm)."""
    state = AgentState(query=query, route="planned", phase="planned")

    # ── 1. Plan (satu LLM call) ──────────────────────────────────────────
    plan, state = _plan(state)

    # ── 2. Eksekusi deterministik (tanpa LLM di antara step) ─────────────
    for i, step in enumerate(plan, 1):
        logger.info("=== Planned step %d/%d: %s ===", i, len(plan), step["tool"])
        state = _execute_step(state, step["tool"], step["args"], i)
        if state.error:
            logger.error("Planned step error: %s", state.error)
            return state

    # ── 2b. Fallback fuzzy (safety net atribut rapuh) ────────────────────
    # Kalau rencana bersandar pada vibe/setting/character (ekstraksi sinopsis)
    # tapi pool-nya sangat sedikit, fuzzy-match term tematik ke judul/kategori
    # mentah yang reliable. Deterministik (tanpa LLM), sejalan dengan semangat
    # planned. Lihat catatan_riset — atribut sinopsis-derived rapuh.
    if _needs_fallback(plan, len(state.enriched_data)):
        keywords = _fallback_keywords(plan, state.query)
        logger.info(
            "Planned pool sparse (%d < %d) — fallback fuzzy judul/kategori: %s",
            len(state.enriched_data), _FALLBACK_MIN_POOL, keywords,
        )
        state = state.model_copy(update={
            "tool_chain_log": state.tool_chain_log + [
                f"planned/fallback: pool sparse ({len(state.enriched_data)}) → "
                f"fuzzy judul|kategori {keywords[:_MAX_FALLBACK_KEYWORDS]}"
            ],
        })
        for j, kw in enumerate(keywords[:_MAX_FALLBACK_KEYWORDS], 1):
            state = _execute_step(
                state, "books_by_title_or_category_fuzzy", {"keyword": kw}, len(plan) + j,
            )
            if state.error:
                logger.error("Planned fallback error: %s", state.error)
                return state
            if len(state.enriched_data) >= _CURATE_TOP_K:
                break

    # ── 3. Curate top-K: urutkan sesuai "paling direkomendasikan" ─────────
    # `enriched_data` mempertahankan urutan merge = urutan kembalian tool, yang
    # setelah fix exact-match-first (tools_catalog.py) sudah "paling relevan
    # dulu" (cocok-persis di depan). `recommendation_order` (shared, dipakai
    # SEMUA arm) menaruh yang tersedia dulu, mempertahankan urutan itu, lalu
    # stamp relevance_score menurun (rank-decay) supaya kartu UI punya angka
    # relevansi bermakna & ordering konsisten lintas arm.
    curated = recommendation_order(state.enriched_data)[:_CURATE_TOP_K]
    state = state.model_copy(update={
        "curated_context": curated,
        "is_finished":     True,
        "tool_chain_log":  state.tool_chain_log + [
            # NB: prefix "planned/curate:" (bukan "planned → ") sengaja — supaya
            # extract_tools_used tidak salah menghitung "curate" sebagai tool.
            f"planned/curate: top {len(curated)} dari pool "
            f"({len(state.enriched_data)}), rank-scored"
        ],
    })

    # ── 4. Responder (synthesis + audit deterministik, TANPA self-correct) ─
    # self_correct=False — A/B audit on/off (catatan_riset.md § 4.1) net-negatif
    # buat retry LLM-nya (AC turun, latency +15-35%, faithfulness ±0.02 tak
    # konsisten). Audit deterministik tetap jalan; env DISABLE_SELF_CORRECT
    # masih bisa override kalau mau balik ke ON.
    logger.info("=== Responder (planned) ===")
    state = responder_node(state, self_correct=False)

    if state.is_hallucinating:
        logger.warning("Planned workflow selesai dengan %d violations.", len(state.violations))
    else:
        logger.info("Planned workflow selesai bersih.")

    return state
