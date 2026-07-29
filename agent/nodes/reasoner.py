"""
Node 1/3 — Reasoner (The Brain of the ReAct Loop)
─────────────────────────────────────────────────────────────────
Tugas:
  Pada setiap putaran loop, baca scratchpad (riwayat Thought/Action/Observation)
  lalu putuskan langkah berikutnya:
    - Pilih tool yang akan dipanggil + argumennya, ATAU
    - Putuskan FINISH karena pool sudah cukup → lanjut ke Responder.

Node ini GENERIK & dipakai beberapa arm lewat parameter `tool_names` +
`base_prompt` (lihat reasoner_node):
  - Search-Space-Gated (agent/core/workflow.py): fase "expand" memberi MENU
    PENUH (seed / multihop / collaborative / vector_search) untuk membentuk
    pool dari nol, lalu fase "curate" mempersempit action space ke shrink-only
    (filter_by_branch/_collection_type/_language, categories_by_author).
  - Pure ReAct / Act-only (workflow_pure_react.py / workflow_act_only.py):
    action space FLAT & konstan (PURE_REACT_TOOLS) dari step pertama.

Reasoner HANYA boleh memilih tool dari `tool_names` yang diberikan workflow;
memilih tool di luar itu dianggap invalid → observation korektif / retry.
`tool_names` (subset agent.tools.CYPHER_TOOLS) + `base_prompt` ditentukan oleh
masing-masing workflow; reasoner tidak tahu arm mana yang memanggilnya.

Output (state):
  - state.next_action    : {"tool": "...", "args": {...}}
  - state.is_finished    : True jika reasoner memilih FINISH
  - state.scratchpad     : appended dengan ReActStep berisi thought baru
  - state.curated_context: jika FINISH, reasoner sudah menetapkan top-K yang dipakai
"""

from __future__ import annotations

import difflib
import json
import logging
from typing import Any

from agent.core.state import AgentState, BookNode, ReActStep, recommendation_order, RECOMMEND_TOP_K
from agent.services.llm_services import llm_json
from agent.tools import build_specs_prompt
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# PROMPT
# ══════════════════════════════════════════════════════════════

_BASE_PROMPT = """You are a navigation/curation agent for a library book
recommendation system. Theme/mood matching (semantic matching) has ALREADY
been resolved before you were called — the candidate pool below is already
thematically relevant (via vector search) or matches the attribute the user
named (via one structured lookup). Your job is ONLY relational
navigation/curation over that pool: narrowing it, reporting on it, or — if
the user mentioned it — extending precision via another attribute combo.
Your goal: make sure the final pool truly matches every criterion in the
user's request, then stop.

Book titles, author names, vibes, settings, and user requests are in Bahasa
Indonesia (Jakarta Public Library catalog) — read and extract them as-is,
do NOT translate entity values.

Neo4j Knowledge Graph ontology:

  (:Author)-[:WROTE]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                            ↓
                   [:BELONGS_TO]->(:Category)
                   [:AVAILABLE_AT]->(:Branch)       ← supernode (1,303 rels)
                   [:CLASSIFIED_AS]->(:DDCClass)     (Dewey code, e.g. "813")
                   [:WRITTEN_IN]->(:Language)
                   [:COLLECTION_TYPE]->(:CollectionType)
                   [:HAS_VIBE]->(:Vibe)
                   [:HAS_SETTING]->(:Setting)
                   [:FEATURES_CHARACTER]->(:Character)

ENTITY -> SEED TOOL MAP — EVERY entity above has a retrieval path; do NOT default to
only vibe/setting/category. Pick the tool whose attribute the query names (combine
them per the entry-point principle when several attributes are named):
  author -> books_by_author        | publisher -> books_by_publisher
  publisher's city -> books_by_publisher_city | category -> books_by_category
  language -> books_by_language     | branch (cabang) -> books_by_branch
  DDC -> books_by_ddc               | collection type -> books_by_collection_type
  vibe / nuansa -> books_by_vibe    | setting / latar -> books_by_setting
  character / tokoh -> books_by_character | a specific title -> lookup_by_title

WORKING PRINCIPLES:
1. Use real entity names (Title, Author, Branch) in your reasoning and
   searches, NEVER internal IDs.
2. Once the target is met, choose action "finish" and list the best book
   titles.
3. TITLE DIVERSITY: when selecting titles, pick DIVERSE books. Do not
   recommend the same book repeatedly just because it's a different
   edition/volume. Look for other relevant title variety in the candidate
   pool.
4. DO NOT HALLUCINATE. Tool arguments must be derived from the user's
   query. If the query doesn't mention an additional attribute, FINISH
   immediately with the current pool.
5. DO NOT REPEAT THE SAME TOOL CALL. If tool X with argument Y just
   returned 0 results / an empty pool, do NOT call it again with the same
   argument — FINISH with what you have.
6. ONE TOOL PER STEP, EXACTLY AS LISTED. Do NOT combine two attributes
   into a tool name that does NOT exist in the list (e.g.
   "books_by_author_and_branch" does NOT exist — that's not a valid
   tool). For vibe+branch or category+branch queries, PREFER the combined
   seed tool (`books_by_vibe_and_branch`, `books_by_category_and_branch`)
   over a separate filter_by_branch step IF the pool is still empty —
   filtering a branch-blind pool (e.g. from vector_search) down to one
   branch routinely collapses it to near-zero, since most of those
   candidates were never checked against that branch. Once the pool
   already has thematic candidates from a prior step, filter_by_branch is
   still the right tool to narrow it by branch. Branch+author has no
   combined tool — that combo ALWAYS goes through filter_by_branch in a
   SEPARATE step after books_by_author.

AVAILABLE TOOLS (grouped under [HEADERS] for clarity only — headers are not
literal syntax, you may still pick any tool from any group):
{tool_specs}

OUTPUT FORMAT — MUST BE A SINGLE JSON OBJECT ONLY. NO opening/closing text,
NO explanation, NO markdown fence. OUTPUT ONLY THIS JSON OBJECT:

{{
  "thought": "Pool already has enough title variety. I'll pick the 5 most diverse and relevant titles.",
  "action": "finish",
  "selected_titles": ["Book Title A", "Book Title B", "Book Title C"]
}}

EXAMPLES:
- Empty pool, query names a category AND a vibe AND a setting (e.g. "Cerita Anak bernuansa keluarga berlatar rumah") ->
  {{"thought": "...", "action": "books_by_vibe_and_setting_and_category", "action_input": {{"vibe": "keluarga", "setting": "rumah", "category": "Cerita Anak"}} }}
- Empty pool, query names a vibe AND a branch (e.g. "buku thriller di Tanjung Duren") ->
  {{"thought": "...", "action": "books_by_vibe_and_branch", "action_input": {{"vibe": "thriller", "branch": "Tanjung Duren"}} }}
- Pool already has thematic candidates, user also mentioned branch "Cikini" ->
  {{"thought": "...", "action": "filter_by_branch", "action_input": {{"branch": "Cikini"}} }}
- Pool already matches all criteria -> TAKE titles from "Status pool kandidat" below:
  {{"thought": "Pool is sufficient, finalizing.", "action": "finish",
    "selected_titles": ["Hujan", "Senja di Jakarta"]}}
  NOTE: selected_titles must be taken EXACTLY from the pool (shown in
  "Status pool kandidat" in the message below), DO NOT invent new titles."""


_PURE_REACT_PROMPT = """You are a fully autonomous library book search/recommendation
agent. There is NO front-door or router outside of you — you decide yourself
whether a query needs semantic search (vector_search) or a specific attribute
lookup in the Knowledge Graph, and you are free to combine both in any order.
The candidate pool starts EMPTY — your first step MUST populate it.

Book titles, author names, vibes, settings, and user queries are in Bahasa
Indonesia (Jakarta Public Library catalog) — read and extract them as-is,
do NOT translate entity values.

Neo4j Knowledge Graph ontology:

  (:Author)-[:WROTE]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                            ↓
                   [:BELONGS_TO]->(:Category)
                   [:AVAILABLE_AT]->(:Branch)       ← supernode (1,303 rels)
                   [:CLASSIFIED_AS]->(:DDCClass)     (Dewey code, e.g. "813")
                   [:WRITTEN_IN]->(:Language)
                   [:COLLECTION_TYPE]->(:CollectionType)
                   [:HAS_VIBE]->(:Vibe)
                   [:HAS_SETTING]->(:Setting)
                   [:FEATURES_CHARACTER]->(:Character)

ENTITY -> SEED TOOL MAP — EVERY entity above has a retrieval path; do NOT default to
only vibe/setting/category. Pick the tool whose attribute the query names (combine
them per the entry-point principle when several attributes are named):
  author -> books_by_author        | publisher -> books_by_publisher
  publisher's city -> books_by_publisher_city | category -> books_by_category
  language -> books_by_language     | branch (cabang) -> books_by_branch
  DDC -> books_by_ddc               | collection type -> books_by_collection_type
  vibe / nuansa -> books_by_vibe    | setting / latar -> books_by_setting
  character / tokoh -> books_by_character | a specific title -> lookup_by_title

WORKING PRINCIPLES:
1. Use real entity names (Title, Author, Branch) in your reasoning and tool
   arguments, NEVER internal IDs.
2. PICK THE RIGHT ENTRY POINT, matching EXACTLY the attributes the query names —
   never add a vibe/setting/category the user did NOT state. Over-specifying (using
   a 3-attribute tool when only 2 were named) invents a phantom constraint and
   returns the WRONG books.
   - Thematic/abstract only (vibe/mood, no concrete attribute) -> `vector_search`.
   - Concrete attribute(s) named -> the matching `books_by_*` tool (see the ENTITY
     MAP above). Combine ONLY the attributes actually present: setting only ->
     `books_by_setting`; vibe+setting -> `books_by_vibe_and_setting`;
     setting+category -> `books_by_setting_and_category`; vibe+setting+category
     (ALL THREE named) -> `books_by_vibe_and_setting_and_category`. Use the
     3-attribute composite ONLY when all three are present — never to fill an
     unstated slot.
   - Books like/similar to a NAMED reference title ("buku lain yang mirip dengan X",
     "buku dengan VIBE/DDC yang SAMA dengan X") -> the COLLABORATIVE tools
     (`books_sharing_vibe_with`, `books_sharing_vibe_with_setting`,
     `books_sharing_ddc_with`), which traverse the graph for an exact shared
     attribute instead of fuzzy embedding similarity.
   - vibe/category + branch ("buku [X] di [cabang]") -> `books_by_vibe_and_branch` /
     `books_by_category_and_branch` DIRECTLY as the first step (a branch-blind
     vector_search pool collapses to near-zero once filtered to one branch).
   GENERIC FILLER WORDS ARE NOT A CATEGORY: "novel", "buku", "cerita", "bacaan",
   "karya" are filler — do NOT pass them as `category`. Only a SPECIFIC named
   category counts ("Cerita Anak", "Dongeng", "Komik", "Fiksi Indonesia", ...).
   GENRE/MOOD WORDS ARE VIBES, not categories: "romance", "misteri", "thriller",
   "komedi", "sejarah", "fantasi", "horor", "petualangan", "biografi" -> pass as
   `vibe`. You may use multiple tools in sequence when the query combines criteria.
3. Once the target is met, choose action "finish" and list the best book titles.
4. TITLE DIVERSITY: when selecting titles, pick DIVERSE books. Do not
   recommend the same book repeatedly just because it's a different
   edition/volume. Look for other relevant title variety in the candidate pool.
5. DO NOT HALLUCINATE. Tool arguments must be derived from the user's query.
   If the query doesn't mention an additional attribute, FINISH immediately
   with the current pool.
6. DO NOT REPEAT THE SAME TOOL CALL. If tool X with argument Y just returned
   0 results / an empty pool, do NOT call it again with the same argument —
   try a different entry point, or FINISH with what you have.
7. ONE TOOL PER STEP, EXACTLY AS LISTED. Do NOT invent tool names that are NOT
   in the list below — in particular, do NOT invent `filter_by_vibe`,
   `filter_by_setting`, or `filter_by_category`. The valid filters are
   `filter_by_branch`, `filter_by_collection_type`, `filter_by_language`, and
   `filter_by_author`. For vibe/setting/category, use `books_by_vibe`,
   `books_by_setting`, `books_by_category`, or their combinations
   (`books_by_vibe_and_setting`, `books_by_vibe_and_setting_and_category`,
   etc.) — NOT a `filter_by_*` tool.

AVAILABLE TOOLS (grouped under [HEADERS] for clarity only — headers are not
literal syntax, you may still pick any tool from any group):
{tool_specs}

OUTPUT FORMAT — MUST BE A SINGLE JSON OBJECT ONLY. NO opening/closing text, NO
explanation, NO markdown fence. OUTPUT ONLY THIS JSON OBJECT:

{{
  "thought": "<your reasoning, Bahasa Indonesia or English, either is fine>",
  "action": "vector_search",
  "action_input": {{"query": "novel romantis berlatar pedesaan"}}
}}

EXAMPLES:
- Thematic/abstract query -> {{"thought": "...", "action": "vector_search", "action_input": {{"query": "<query text>"}} }}
- Query naming a specific author -> {{"thought": "...", "action": "books_by_author", "action_input": {{"author": "Tere Liye"}} }}
- "[Kategori] bernuansa [vibe] berlatar [setting]" (category + vibe + setting, 3 attributes) -> {{"thought": "...", "action": "books_by_vibe_and_setting_and_category", "action_input": {{"vibe": "keluarga", "setting": "rumah", "category": "Cerita Anak"}} }}
- "Novel bertema petualangan berlatar perkotaan" ("Novel" = filler word, NOT a category; only vibe + setting are named) -> {{"thought": "...", "action": "books_by_vibe_and_setting", "action_input": {{"vibe": "petualangan", "setting": "perkotaan"}} }}
- "Ada buku lain dengan nuansa serupa <Judul>?" -> {{"thought": "...", "action": "books_sharing_vibe_with", "action_input": {{"title": "<Judul>"}} }}
- "Buku lain dengan klasifikasi DDC yang sama dengan <Judul>?" -> {{"thought": "...", "action": "books_sharing_ddc_with", "action_input": {{"title": "<Judul>"}} }}
- "Buku thriller apa yang tersedia di Perpustakaan ... - Tanjung Duren?" -> {{"thought": "...", "action": "books_by_vibe_and_branch", "action_input": {{"vibe": "thriller", "branch": "Tanjung Duren"}} }}
- Pool already has candidates, user also mentioned branch "Cikini" ->
  {{"thought": "...", "action": "filter_by_branch", "action_input": {{"branch": "Cikini"}} }}
- Pool already matches all criteria -> TAKE titles from "Status pool kandidat" below:
  {{"thought": "Pool is sufficient, finalizing.", "action": "finish",
    "selected_titles": ["Hujan", "Senja di Jakarta"]}}
  NOTE: selected_titles must be taken EXACTLY from the pool (shown in "Status
  pool kandidat" in the message below), DO NOT invent new titles."""


# Act-only ablation (workflow_act_only.py): sengaja identik kata-per-kata
# dengan _PURE_REACT_PROMPT KECUALI channel reasoning — tidak ada field
# "thought" di output format/examples, dan model dilarang menulis penalaran.
# Satu-satunya variabel yang berubah antara arm pure_react dan act_only
# adalah interleaved CoT, sesuai baseline "Act" di paper ReAct (Yao et al.).
_ACT_ONLY_PROMPT = """You are a fully autonomous library book search/recommendation
agent. There is NO front-door or router outside of you — you decide yourself
whether a query needs semantic search (vector_search) or a specific attribute
lookup in the Knowledge Graph, and you are free to combine both in any order.
The candidate pool starts EMPTY — your first step MUST populate it.

Book titles, author names, vibes, settings, and user queries are in Bahasa
Indonesia (Jakarta Public Library catalog) — read and extract them as-is,
do NOT translate entity values.

Neo4j Knowledge Graph ontology:

  (:Author)-[:WROTE]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                            ↓
                   [:BELONGS_TO]->(:Category)
                   [:AVAILABLE_AT]->(:Branch)       ← supernode (1,303 rels)
                   [:CLASSIFIED_AS]->(:DDCClass)     (Dewey code, e.g. "813")
                   [:WRITTEN_IN]->(:Language)
                   [:COLLECTION_TYPE]->(:CollectionType)
                   [:HAS_VIBE]->(:Vibe)
                   [:HAS_SETTING]->(:Setting)
                   [:FEATURES_CHARACTER]->(:Character)

ENTITY -> SEED TOOL MAP — EVERY entity above has a retrieval path; do NOT default to
only vibe/setting/category. Pick the tool whose attribute the query names (combine
them per the entry-point principle when several attributes are named):
  author -> books_by_author        | publisher -> books_by_publisher
  publisher's city -> books_by_publisher_city | category -> books_by_category
  language -> books_by_language     | branch (cabang) -> books_by_branch
  DDC -> books_by_ddc               | collection type -> books_by_collection_type
  vibe / nuansa -> books_by_vibe    | setting / latar -> books_by_setting
  character / tokoh -> books_by_character | a specific title -> lookup_by_title

WORKING PRINCIPLES:
1. Use real entity names (Title, Author, Branch) in your tool arguments,
   NEVER internal IDs.
2. PICK THE RIGHT ENTRY POINT, matching EXACTLY the attributes the query names —
   never add a vibe/setting/category the user did NOT state. Over-specifying (using
   a 3-attribute tool when only 2 were named) invents a phantom constraint and
   returns the WRONG books.
   - Thematic/abstract only (vibe/mood, no concrete attribute) -> `vector_search`.
   - Concrete attribute(s) named -> the matching `books_by_*` tool (see the ENTITY
     MAP above). Combine ONLY the attributes actually present: setting only ->
     `books_by_setting`; vibe+setting -> `books_by_vibe_and_setting`;
     setting+category -> `books_by_setting_and_category`; vibe+setting+category
     (ALL THREE named) -> `books_by_vibe_and_setting_and_category`. Use the
     3-attribute composite ONLY when all three are present — never to fill an
     unstated slot.
   - Books like/similar to a NAMED reference title ("buku lain yang mirip dengan X",
     "buku dengan VIBE/DDC yang SAMA dengan X") -> the COLLABORATIVE tools
     (`books_sharing_vibe_with`, `books_sharing_vibe_with_setting`,
     `books_sharing_ddc_with`), which traverse the graph for an exact shared
     attribute instead of fuzzy embedding similarity.
   - vibe/category + branch ("buku [X] di [cabang]") -> `books_by_vibe_and_branch` /
     `books_by_category_and_branch` DIRECTLY as the first step (a branch-blind
     vector_search pool collapses to near-zero once filtered to one branch).
   GENERIC FILLER WORDS ARE NOT A CATEGORY: "novel", "buku", "cerita", "bacaan",
   "karya" are filler — do NOT pass them as `category`. Only a SPECIFIC named
   category counts ("Cerita Anak", "Dongeng", "Komik", "Fiksi Indonesia", ...).
   GENRE/MOOD WORDS ARE VIBES, not categories: "romance", "misteri", "thriller",
   "komedi", "sejarah", "fantasi", "horor", "petualangan", "biografi" -> pass as
   `vibe`. You may use multiple tools in sequence when the query combines criteria.
3. Once the target is met, choose action "finish" and list the best book titles.
4. TITLE DIVERSITY: when selecting titles, pick DIVERSE books. Do not
   recommend the same book repeatedly just because it's a different
   edition/volume. Look for other relevant title variety in the candidate pool.
5. DO NOT HALLUCINATE. Tool arguments must be derived from the user's query.
   If the query doesn't mention an additional attribute, FINISH immediately
   with the current pool.
6. DO NOT REPEAT THE SAME TOOL CALL. If tool X with argument Y just returned
   0 results / an empty pool, do NOT call it again with the same argument —
   try a different entry point, or FINISH with what you have.
7. ONE TOOL PER STEP, EXACTLY AS LISTED. Do NOT invent tool names that are NOT
   in the list below — in particular, do NOT invent `filter_by_vibe`,
   `filter_by_setting`, or `filter_by_category`. The valid filters are
   `filter_by_branch`, `filter_by_collection_type`, `filter_by_language`, and
   `filter_by_author`. For vibe/setting/category, use `books_by_vibe`,
   `books_by_setting`, `books_by_category`, or their combinations
   (`books_by_vibe_and_setting`, `books_by_vibe_and_setting_and_category`,
   etc.) — NOT a `filter_by_*` tool.

AVAILABLE TOOLS (grouped under [HEADERS] for clarity only — headers are not
literal syntax, you may still pick any tool from any group):
{tool_specs}

OUTPUT FORMAT — MUST BE A SINGLE JSON OBJECT ONLY. NO opening/closing text, NO
explanation, NO markdown fence, and NO "thought" field or reasoning text of
ANY kind — output ONLY the action object:

{{
  "action": "vector_search",
  "action_input": {{"query": "novel romantis berlatar pedesaan"}}
}}

EXAMPLES:
- Thematic/abstract query -> {{"action": "vector_search", "action_input": {{"query": "<query text>"}} }}
- Query naming a specific author -> {{"action": "books_by_author", "action_input": {{"author": "Tere Liye"}} }}
- "[Kategori] bernuansa [vibe] berlatar [setting]" (category + vibe + setting, 3 attributes) -> {{"action": "books_by_vibe_and_setting_and_category", "action_input": {{"vibe": "keluarga", "setting": "rumah", "category": "Cerita Anak"}} }}
- "Novel bertema petualangan berlatar perkotaan" ("Novel" = filler word, NOT a category; only vibe + setting are named) -> {{"action": "books_by_vibe_and_setting", "action_input": {{"vibe": "petualangan", "setting": "perkotaan"}} }}
- "Ada buku lain dengan nuansa serupa <Judul>?" -> {{"action": "books_sharing_vibe_with", "action_input": {{"title": "<Judul>"}} }}
- "Buku lain dengan klasifikasi DDC yang sama dengan <Judul>?" -> {{"action": "books_sharing_ddc_with", "action_input": {{"title": "<Judul>"}} }}
- "Buku thriller apa yang tersedia di Perpustakaan ... - Tanjung Duren?" -> {{"action": "books_by_vibe_and_branch", "action_input": {{"vibe": "thriller", "branch": "Tanjung Duren"}} }}
- Pool already has candidates, user also mentioned branch "Cikini" ->
  {{"action": "filter_by_branch", "action_input": {{"branch": "Cikini"}} }}
- Pool already matches all criteria -> TAKE titles from "Status pool kandidat" below:
  {{"action": "finish", "selected_titles": ["Hujan", "Senja di Jakarta"]}}
  NOTE: selected_titles must be taken EXACTLY from the pool (shown in "Status
  pool kandidat" in the message below), DO NOT invent new titles."""


# Curate-phase prompt untuk Search-Space-Gated workflow (workflow.py). Setelah
# SATU seed retrieval, action space jadi shrink-only — tak ada tool retrieval
# yang tersedia. Memakai _PURE_REACT_PROMPT di sini bikin model kecil buang
# step mencoba books_by_* / vector_search / combo yang diblok (invalid → retry
# → latency meledak, terlihat 91s di smoke test). Curate karena itu punya
# prompt ketat sendiri: filter atau finish, JANGAN retrieve.
_CURATE_PROMPT = """You are curating an ALREADY-FORMED candidate pool for a library
book recommendation system. Retrieval is DONE — the pool below already holds the
matched candidates. Your ONLY remaining job is to NARROW the pool to exactly what
the user asked, then finish.

Book titles, author names, and user requests are in Bahasa Indonesia — read
entity values as-is, do NOT translate them.

WORKING PRINCIPLES:
1. You may ONLY narrow or report, NEVER retrieve. Valid actions are the
   filter/report tools listed below plus "finish". Do NOT call any books_by_*,
   vector_search, or combined *_and_* tool — they are NOT available now and will
   be rejected. For a branch / collection-type / language / author the user
   named that is not yet applied, use the matching filter_by_* tool ONCE.
2. DO NOT HALLUCINATE filter arguments. Filter ONLY by an attribute the user
   explicitly named. If the query names no further branch/collection-type/
   language, or the pool already satisfies it, choose "finish" immediately.
3. DO NOT REPEAT a filter that just returned 0 results — finish with what you
   have instead.
4. TITLE DIVERSITY: pick diverse titles, not repeated editions of one book.

AVAILABLE TOOLS:
{tool_specs}

OUTPUT FORMAT — a SINGLE JSON object ONLY, no prose, no markdown fence:

{{
  "thought": "Pool already matches the request; no further filter needed.",
  "action": "finish",
  "selected_titles": ["Book Title A", "Book Title B"]
}}

EXAMPLES:
- Pool ready, user also named branch "Cikini" not yet applied ->
  {{"thought": "...", "action": "filter_by_branch", "action_input": {{"branch": "Cikini"}} }}
- Pool already satisfies every criterion -> TAKE titles from "Status pool kandidat" below:
  {{"thought": "Pool sufficient, finalizing.", "action": "finish",
    "selected_titles": ["Hujan", "Senja di Jakarta"]}}
  NOTE: selected_titles must be taken EXACTLY from the pool shown below; do NOT invent titles."""


_USER_TEMPLATE = """Permintaan pengguna:
"{query}"

Status pool kandidat saat ini: {pool_summary}

Riwayat ReAct (Thought/Action/Observation sejauh ini):
{scratchpad}

Tentukan langkah BERIKUTNYA. Output HARUS satu objek JSON valid sesuai format."""


# ══════════════════════════════════════════════════════════════
# JSON PARSING (toleran terhadap markdown wrapping & noise)
# ══════════════════════════════════════════════════════════════

def _scan_json_objects(text: str) -> list[str]:
    """
    Scan brace-balanced JSON object candidates dari teks (string-aware).
    Lebih robust daripada regex greedy untuk LLM output yang berisik.
    """
    out: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False

    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    out.append(text[start: i + 1])
                    start = -1
    return out


def _extract_json(content: str) -> dict[str, Any]:
    """Ekstrak objek JSON dari output LLM, tahan banting markdown / prefix / noise."""
    if not content:
        raise ValueError("LLM mengembalikan output kosong")

    cleaned = content.strip()

    # 1) Coba langsung
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2) Strip markdown fence
    if "```" in cleaned:
        for part in cleaned.split("```"):
            p = part.strip()
            if p.lower().startswith("json"):
                p = p[4:].lstrip()
            if p.startswith("{"):
                try:
                    return json.loads(p)
                except json.JSONDecodeError:
                    cleaned = p
                    break

    # 3) Brace-balanced scan — pilih blok valid pertama yang parse-able
    for candidate in _scan_json_objects(cleaned):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Tidak ada objek JSON valid di output LLM: {content[:200]!r}")


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _pool_summary(state: AgentState) -> str:
    n = len(state.enriched_data)
    if n == 0:
        return "kosong (belum ada kandidat)"
    samples = "; ".join(
        f'"{b.title[:40]}"'
        for b in state.enriched_data[:5]
    )
    return f"{n} buku terkumpul. Contoh judul valid: [{samples}]"


def _format_scratchpad(state: AgentState) -> str:
    if not state.scratchpad:
        return "(belum ada langkah)"
    return "\n\n".join(s.to_prompt_block() for s in state.scratchpad[-5:])
    # batasi 5 langkah terakhir agar prompt tidak meledak


def _select_curated(state: AgentState, selected_titles: list[str]) -> list[BookNode]:
    """
    Pilih buku dari pool sesuai judul yang ditunjuk reasoner.
    Fallback: top-N berdasarkan relevance_score jika reasoner tidak menyebut judul valid.
    """
    pool = state.enriched_data
    if not pool:
        return []

    if selected_titles:
        title_to_book = {b.title.lower(): b for b in pool}
        chosen = [title_to_book[t.lower()] for t in selected_titles if t.lower() in title_to_book]
        if chosen:
            # recommendation_order (shared, semua arm): tersedia dulu, urutan
            # pilihan reasoner dipertahankan, + relevance_score menurun bermakna.
            return recommendation_order(chosen)[:RECOMMEND_TOP_K]

    # Fallback: seluruh pool, di-order sama supaya UI/P@K konsisten lintas arm.
    return recommendation_order(pool)[:RECOMMEND_TOP_K]


# ══════════════════════════════════════════════════════════════
# NODE
# ══════════════════════════════════════════════════════════════

def reasoner_node(
    state: AgentState, *, tool_names: list[str], base_prompt: str | None = None,
) -> AgentState:
    """Ambil keputusan ReAct berikutnya berdasarkan scratchpad + pool.

    `tool_names`: subset CYPHER_TOOLS yang boleh dipilih untuk langkah ini
    (ditentukan workflow.py dari state.route + state.phase).

    `base_prompt`: system prompt template (harus punya placeholder
    `{tool_specs}`). Setiap workflow mengoper prompt-nya sendiri:
    Search-Space-Gated → `_PURE_REACT_PROMPT` (expand) / `_CURATE_PROMPT`
    (curate); pure-ReAct → `_PURE_REACT_PROMPT`; act-only → `_ACT_ONLY_PROMPT`.
    Default None jatuh ke `_BASE_PROMPT`, TAPI itu praktis tak pernah terpakai
    (semua workflow selalu mengoper base_prompt eksplisit). Semua logika
    parsing/FINISH/stuck-loop di bawah tetap sama; hanya teks prompt yang beda.
    """
    pool_str = _pool_summary(state)
    scratch_str = _format_scratchpad(state)

    prompt_template = base_prompt if base_prompt is not None else _BASE_PROMPT
    system_prompt = prompt_template.format(tool_specs=build_specs_prompt(tool_names))
    user_msg = _USER_TEMPLATE.format(
        query=state.query,
        pool_summary=pool_str,
        scratchpad=scratch_str,
    )

    try:
        response = llm_json.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])
        raw = getattr(response, "content", "") or ""
        state = state.model_copy(update={"token_usage": state.token_usage.add(response)})
        decision = _extract_json(raw)
    except Exception as exc:
        # Retry sekali dengan reminder eksplisit ke format JSON
        logger.warning("Reasoner parse-fail: %s — retry sekali dengan reminder.", exc)
        try:
            retry_user = (
                user_msg
                + "\n\nPENTING: outputmu sebelumnya GAGAL diparse sebagai JSON. "
                  "Sekarang KELUARKAN HANYA satu objek JSON valid sesuai skema. "
                  "JANGAN tambahkan teks 'Berikut adalah...', 'Thought:', atau apapun di luar braces."
            )
            response = llm_json.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=retry_user),
            ])
            raw = getattr(response, "content", "") or ""
            state = state.model_copy(update={"token_usage": state.token_usage.add(response)})
            decision = _extract_json(raw)
        except Exception as exc2:
            logger.warning(
                "Reasoner gagal lagi (%s) — paksa FINISH dengan pool saat ini.", exc2,
            )
            next_step_idx = state.react_step + 1
            fallback_step = ReActStep(
                step=next_step_idx,
                thought=f"(parse-fail x2: {exc2})",
                action="finish",
                action_input={},
                observation="Reasoner gagal parse JSON dua kali — paksa FINISH dengan pool sekarang.",
            )
            curated = _select_curated(state, [])
            return state.model_copy(update={
                "scratchpad":      state.scratchpad + [fallback_step],
                "react_step":      next_step_idx,
                "is_finished":     True,
                "next_action":     None,
                "curated_context": curated,
                "tool_chain_log":  state.tool_chain_log + [
                    f"reasoner #{next_step_idx} → parse-fail x2, force FINISH ({len(curated)} curated)"
                ],
                "reasoning_log":   state.reasoning_log + [
                    f"#{next_step_idx} (parse-fail x2) {exc2}"
                ],
                "error":           None,
            })

    thought = str(decision.get("thought") or "").strip()
    action = str(decision.get("action") or "").strip().lower()
    action_input = decision.get("action_input") or {}
    if not isinstance(action_input, dict):
        action_input = {}

    next_step_idx = state.react_step + 1
    new_scratch_step = ReActStep(
        step=next_step_idx,
        thought=thought,
        action=action,
        action_input=action_input,
        observation="",  # akan diisi oleh tool_executor
    )

    # ── FINISH branch ─────────────────────────────────────────────────────
    if action == "finish":
        selected_titles = decision.get("selected_titles") or []
        if not isinstance(selected_titles, list):
            selected_titles = []
        curated = _select_curated(state, [str(x) for x in selected_titles])

        # Observasi penutup — supaya scratchpad lengkap untuk audit
        new_scratch_step = new_scratch_step.model_copy(update={
            "observation": (
                f"FINISH dipilih. {len(curated)} buku masuk curated_context: "
                + ", ".join(b.book_id for b in curated)
                if curated else "FINISH dipilih tapi pool kosong."
            )
        })

        logger.info(
            "Reasoner: FINISH @ step=%d, curated=%d, pool=%d",
            next_step_idx, len(curated), len(state.enriched_data),
        )

        return state.model_copy(update={
            "scratchpad":      state.scratchpad + [new_scratch_step],
            "react_step":      next_step_idx,
            "is_finished":     True,
            "next_action":     None,
            "curated_context": curated,
            "tool_chain_log":  state.tool_chain_log + [
                f"reasoner #{next_step_idx} → FINISH ({len(curated)} curated)"
            ],
            "reasoning_log":   state.reasoning_log + [f"#{next_step_idx} {thought}"],
            "error":           None,
        })

    # ── Validasi action berada di subset yang diizinkan ──────────────────
    if action not in tool_names:
        # Mengulang persis action tidak valid yang sama dua kali → model
        # tidak akan koreksi sendiri (terlihat di praktik dengan model 8B
        # kecil) — daripada habiskan sisa MAX_REACT_STEPS, paksa FINISH.
        prev = state.scratchpad[-1] if state.scratchpad else None
        if prev and prev.action == action and prev.action_input == action_input:
            logger.warning("Reasoner mengulang action TIDAK VALID '%s' — paksa FINISH.", action)
            curated = _select_curated(state, [])
            stuck_step = new_scratch_step.model_copy(update={
                "observation": f"Action '{action}' tetap tidak valid setelah retry. Paksa FINISH.",
            })
            return state.model_copy(update={
                "scratchpad":      state.scratchpad + [stuck_step],
                "react_step":      next_step_idx,
                "is_finished":     True,
                "next_action":     None,
                "curated_context": curated,
                "tool_chain_log":  state.tool_chain_log + [
                    f"reasoner #{next_step_idx} → invalid action diulang, force FINISH ({len(curated)} curated)"
                ],
                "reasoning_log":   state.reasoning_log + [
                    f"#{next_step_idx} invalid action diulang → force FINISH"
                ],
                "error":           None,
            })

        # Beri observation informatif, biarkan loop lanjut — reasoner bisa
        # baca scratchpad dan koreksi pemilihan tool di iterasi berikut.
        # Untuk model kecil (7B/8B) yang sering "stuck" setelah tool tidak
        # valid, tambahkan saran tool terdekat (fuzzy match) supaya koreksi
        # di iterasi berikut lebih terarah, bukan menebak buta lalu mentok.
        available = ", ".join(sorted(tool_names))
        suggestions = difflib.get_close_matches(action, tool_names, n=3, cutoff=0.4)
        hint = f" Mungkin maksudmu: {', '.join(suggestions)}." if suggestions else ""
        observation = (
            f"Action '{action}' tidak tersedia di langkah ini.{hint} "
            f"Pilih dari: {available}, atau 'finish'."
        )
        new_scratch_step = new_scratch_step.model_copy(update={
            "observation": observation,
        })

        logger.warning("Reasoner memilih action tidak dikenal '%s' — minta retry.", action)
        return state.model_copy(update={
            "scratchpad":     state.scratchpad + [new_scratch_step],
            "react_step":     next_step_idx,
            "next_action":    None,        # tool_executor skip
            "is_finished":    False,       # loop lanjut, reasoner punya kesempatan koreksi
            "tool_chain_log": state.tool_chain_log + [
                f"reasoner #{next_step_idx} → unknown action '{action}', minta retry"
            ],
            "reasoning_log":  state.reasoning_log + [
                f"#{next_step_idx} {thought} (action invalid → retry)"
            ],
            "error":          None,
        })

    logger.info(
        "Reasoner #%d: action=%s args=%s",
        next_step_idx, action, action_input,
    )

    # ── Deteksi pengulangan tidak produktif → langsung FINISH ────────────
    # Kalau aksi yang sama diulang padahal observasi sebelumnya "0 hasil"/
    # "0 buku", model kecil cenderung mentok — hentikan dengan FINISH memakai
    # pool saat ini alih-alih membuang sisa MAX_REACT_STEPS.
    if state.scratchpad:
        prev = state.scratchpad[-1]
        same_action = (prev.action == action and prev.action_input == action_input)
        prev_unproductive = (
            "0 hasil" in prev.observation
            or "0 buku" in prev.observation
            or "0/" in prev.observation
        )
        if same_action and prev_unproductive:
            logger.warning("Reasoner mengulang aksi tidak produktif — paksa FINISH.")
            curated = _select_curated(state, [])
            stuck_step = new_scratch_step.model_copy(update={
                "observation": "Aksi diulang tanpa hasil baru. Paksa FINISH.",
            })
            return state.model_copy(update={
                "scratchpad":      state.scratchpad + [stuck_step],
                "react_step":      next_step_idx,
                "is_finished":     True,
                "next_action":     None,
                "curated_context": curated,
                "tool_chain_log":  state.tool_chain_log + [
                    f"reasoner #{next_step_idx} → stuck-loop, force FINISH ({len(curated)} curated)"
                ],
                "reasoning_log":   state.reasoning_log + [
                    f"#{next_step_idx} stuck loop → force FINISH"
                ],
                "error":           None,
            })

    return state.model_copy(update={
        "scratchpad":     state.scratchpad + [new_scratch_step],
        "react_step":     next_step_idx,
        "next_action":    {"tool": action, "args": action_input},
        "is_finished":    False,
        "tool_chain_log": state.tool_chain_log + [
            f"reasoner #{next_step_idx} → {action}({action_input})"
        ],
        "reasoning_log":  state.reasoning_log + [f"#{next_step_idx} {thought}"],
        "error":          None,
    })
