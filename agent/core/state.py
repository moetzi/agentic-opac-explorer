"""
agent/core/state.py — Pydantic v2 State Schema (shared across ReAct arms)
─────────────────────────────────────────────────────────────────────────
State bersama semua arm (Search-Space-Gated, Pure ReAct, Act-only, Planned):

    query → reasoner/planner ⇄ tool_executor (expand→curate) → responder

Ontology graf yang dirujuk:

    (:Author)-[:WROTE]->(:Book)-[:PUBLISHED_BY]->(:Publisher)
                              ↓
                         [:BELONGS_TO]->(:Category)
                         [:AVAILABLE_AT]->(:Branch)       ← Supernode
                         [:CLASSIFIED_AS]->(:DDCClass)
                         [:HAS_VIBE]->(:Vibe)
                         [:HAS_SETTING]->(:Setting)
                         [:FEATURES_CHARACTER]->(:Character)

Field di state ini sengaja superset: data class lama (intent, entry_point,
graph_intent, assembly_draft, dst.) tetap ada dengan default kosong supaya
konsumen lama (Streamlit UI, evaluator) tidak rusak.
"""

import operator
from typing import Annotated, Any, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════
# 1. ONTOLOGY NODE MODELS
# ══════════════════════════════════════════════════════════════

class AuthorNode(BaseModel):
    """(:Author) — bisa penulis, penerjemah, atau ilustrator."""
    name: str
    role: str = Field(default="penulis", description="penulis | penerjemah | ilustrator")


class PublisherNode(BaseModel):
    """(:Publisher)"""
    name: str
    city: Optional[str] = None


class BranchNode(BaseModel):
    """(:Branch) — lokasi fisik perpustakaan. SUPERNODE: avg 1.303 relasi."""
    name: str


class CategoryNode(BaseModel):
    """(:Category) — Fiksi, Non-Fiksi, Agama, dll."""
    name: str


class VibeNode(BaseModel):
    """(:Vibe) — nuansa buku: Misteri, Romance, Thriller, dsb."""
    name: str


class SettingNode(BaseModel):
    """(:Setting) — latar cerita: Pedesaan, Perkotaan, Sekolah, Kerajaan, dsb."""
    name: str


class CharacterNode(BaseModel):
    """(:Character) — tokoh dalam buku."""
    name: str


# ══════════════════════════════════════════════════════════════
# 2. BOOK NODE — pusat ontologi
# ══════════════════════════════════════════════════════════════

class BookNode(BaseModel):
    """
    (:Book) — node inti, semua relasi berakar di sini.
    """

    # ── Core properties (:Book) ──────────────────────────────────────────
    book_id: str          = Field(..., min_length=1)
    title: str            = Field(..., min_length=1)
    isbn_13: Optional[str]  = Field(default=None)
    pub_year: Optional[int] = Field(default=None)
    total_pages: Optional[int] = Field(default=None, ge=0)
    abstract_clean: Optional[str] = Field(default=None)
    is_fiction: bool      = Field(default=False)
    cover_url: Optional[str] = Field(default=None)
    ddc_class: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None)
    edisi: Optional[str] = Field(default=None)

    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # ── Relasi ontologi (hasil multi-hop traversal) ──────────────────────
    authors: List[AuthorNode]       = Field(default_factory=list)   # [:WROTE]
    publisher: Optional[PublisherNode] = Field(default=None)        # [:PUBLISHED_BY]
    categories: List[CategoryNode]  = Field(default_factory=list)   # [:BELONGS_TO]
    branches: List[BranchNode]      = Field(default_factory=list)   # [:AVAILABLE_AT]
    vibes: List[VibeNode]           = Field(default_factory=list)   # [:HAS_VIBE]
    settings: List[SettingNode]     = Field(default_factory=list)   # [:HAS_SETTING]
    characters: List[CharacterNode] = Field(default_factory=list)   # [:FEATURES_CHARACTER]

    # ── Validators ───────────────────────────────────────────────────────
    @field_validator("relevance_score", mode="before")
    @classmethod
    def clamp_score(cls, v: object) -> float:
        if not isinstance(v, (int, float, str, bytes, bytearray)):
            return 0.0
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("pub_year", mode="before")
    @classmethod
    def coerce_year(cls, v: object) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(str(v)[:4])
        except (ValueError, TypeError):
            return None

    # ── Computed properties ───────────────────────────────────────────────
    @property
    def is_available(self) -> bool:
        return len(self.branches) > 0

    @property
    def available_at(self) -> list[str]:
        return [b.name for b in self.branches]

    @property
    def author_names(self) -> list[str]:
        return [a.name for a in self.authors]

    @property
    def vibe_names(self) -> list[str]:
        return [v.name for v in self.vibes]

    @property
    def setting_names(self) -> list[str]:
        return [s.name for s in self.settings]

    def to_prompt_line(self) -> str:
        stock_label = f"✅ {', '.join(self.available_at)}" if self.is_available else "❌ Tidak tersedia"
        authors_str  = ", ".join(self.author_names) or "Unknown"
        vibes_str    = ", ".join(self.vibe_names) or "-"
        settings_str = ", ".join(self.setting_names) or "-"
        return (
            f"[{self.book_id}] \"{self.title}\" | "
            f"Penulis: {authors_str} | "
            f"Vibe: {vibes_str} | Latar: {settings_str} | "
            f"Stok: {stock_label} | Skor: {self.relevance_score:.3f}"
        )

    model_config = {"arbitrary_types_allowed": True}


# Backward compat alias
BookMetadata = BookNode


# ══════════════════════════════════════════════════════════════
# 3. GRAPH QUERY INTENT — ringkasan rencana traversal (untuk UI debug)
# ══════════════════════════════════════════════════════════════

GraphEntryNode = Literal[
    "book_similar", "setting", "vibe", "character",
    "category", "author", "publisher", "vector_semantic",
]

class GraphQueryIntent(BaseModel):
    """
    Hasil ringkasan rencana traversal — di arsitektur ReAct ini diisi oleh
    Reasoner berdasarkan tool_calls yang sudah dipilih. Bukan lagi sumber
    kebenaran (sumber kebenaran = scratchpad), tapi tetap dipakai UI untuk
    menampilkan summary "traversal yang dilakukan".
    """
    entry_nodes: List[GraphEntryNode] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    branch_filter: Optional[str] = Field(default=None)
    reference_book_title: Optional[str] = Field(default=None)

    @property
    def traversal_order(self) -> List[str]:
        priority = {
            "book_similar": 1, "setting": 2, "vibe": 2, "character": 2,
            "category": 3, "author": 3, "publisher": 4, "vector_semantic": 5,
        }
        ordered = sorted(self.entry_nodes, key=lambda n: priority.get(n, 9))
        return [str(n) for n in ordered]


# ══════════════════════════════════════════════════════════════
# 4. POLICY VIOLATION
# ══════════════════════════════════════════════════════════════

class PolicyViolation(BaseModel):
    violation_type: str           = Field(..., description="hallucinated_title | wrong_author | wrong_stock | wrong_branch | wrong_vibe")
    detail: str
    offending_text: Optional[str] = Field(default=None)

    def __str__(self) -> str:
        return f"[{self.violation_type}] {self.detail}"


class TokenUsage(BaseModel):
    """Akumulasi token yang dikonsumsi LLM sepanjang satu workflow run."""
    input_tokens: int  = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int  = Field(default=0, ge=0)

    def add(self, response_obj) -> "TokenUsage":
        """Tambahkan token dari satu LLM response (LangChain AIMessage)."""
        meta = getattr(response_obj, "usage_metadata", None) or {}
        # LangChain key names vary slightly across providers
        inp = int(
            meta.get("input_tokens") or
            meta.get("prompt_tokens") or 0
        )
        out = int(
            meta.get("output_tokens") or
            meta.get("completion_tokens") or 0
        )
        total = int(
            meta.get("total_tokens") or
            meta.get("total_token_count") or
            (inp + out)
        )
        return TokenUsage(
            input_tokens=self.input_tokens + inp,
            output_tokens=self.output_tokens + out,
            total_tokens=self.total_tokens + total,
        )


# ══════════════════════════════════════════════════════════════
# 5. REACT SCRATCHPAD ENTRY
# ══════════════════════════════════════════════════════════════

class ReActStep(BaseModel):
    """Satu putaran Thought → Action → Observation di ReAct loop."""
    step: int
    thought: str          = Field(default="")
    action: str           = Field(default="")
    action_input: dict    = Field(default_factory=dict)
    observation: str      = Field(default="")

    def to_prompt_block(self) -> str:
        ai = self.action_input or {}
        return (
            f"Thought {self.step}: {self.thought}\n"
            f"Action {self.step}: {self.action}({ai})\n"
            f"Observation {self.step}: {self.observation}"
        )


# ══════════════════════════════════════════════════════════════
# 6. AGENT STATE
# ══════════════════════════════════════════════════════════════

class AgentState(BaseModel):
    """
    State utama bersama semua arm ReAct.

    Field kontrol alur:
      - route           : id arm/alur ("search_space_gated" | "planned" | ...)
      - phase           : "expand" | "curate" — di Search-Space-Gated menentukan
                          apakah action space masih menu penuh (expand) atau
                          shrink-only (curate)

    Field ReAct:
      - scratchpad      : riwayat (thought, action, observation)
      - next_action     : action yang akan dieksekusi tool_executor
      - react_step      : counter loop
      - is_finished     : flag bahwa reasoner sudah memutuskan FINISH

    Field lama (di-keep dengan default kosong untuk kompatibilitas UI &
    evaluator yang sudah ada):
      - intent, entry_point, graph_intent
      - assembly_draft, needs_more_info, additional_query
      - fallback_reason
    """

    # ── Input ──────────────────────────────────────────────────────────────
    query: str       = Field(default="")
    intent: str      = Field(default="react")     # diisi oleh Reasoner di akhir loop
    entry_point: str = Field(default="agent")     # selalu "agent" (autonomous)

    # ── Alur / arm control ─────────────────────────────────────────────────
    route: Optional[str] = Field(default=None, description="arm id, mis. 'search_space_gated' | 'planned'")
    phase: str            = Field(default="seed", description="'seed' | 'curate'")

    # ── Graph traversal summary (diisi Reasoner berdasarkan jejak tool) ───
    graph_intent: Optional[GraphQueryIntent] = Field(default=None)

    # ── Conversation ──────────────────────────────────────────────────────
    messages: Annotated[List[dict], operator.add] = Field(default_factory=list)

    # ── Tool outputs (pool kandidat buku) ─────────────────────────────────
    ids_from_vector: List[str]      = Field(default_factory=list)
    enriched_data: List[BookNode]   = Field(default_factory=list)
    curated_context: List[BookNode] = Field(default_factory=list)

    # ── Generation ────────────────────────────────────────────────────────
    assembly_draft: str         = Field(default="")
    needs_more_info: bool       = Field(default=False)
    additional_query: Optional[str] = Field(default=None)
    final_answer: str           = Field(default="")

    # ── Policy / Audit ────────────────────────────────────────────────────
    is_hallucinating: bool            = Field(default=False)
    violations: List[PolicyViolation] = Field(default_factory=list)
    fallback_reason: Optional[str]    = Field(default=None)
    retry_count: int                  = Field(default=0, ge=0)

    # ── ReAct loop ────────────────────────────────────────────────────────
    scratchpad: List[ReActStep]    = Field(default_factory=list)
    next_action: Optional[dict]    = Field(default=None)
    react_step: int                = Field(default=0, ge=0)
    is_finished: bool              = Field(default=False)

    # ── Observability ─────────────────────────────────────────────────────
    reasoning_log: Annotated[List[str], operator.add]  = Field(default_factory=list)
    tool_chain_log: Annotated[List[str], operator.add] = Field(default_factory=list)

    # ── Token cost tracking ───────────────────────────────────────────────
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    # ── Error ─────────────────────────────────────────────────────────────
    error: Optional[str] = Field(default=None)

    model_config = {"arbitrary_types_allowed": True}

    # ── Helpers ───────────────────────────────────────────────────────────

    def log_step(self, msg: str) -> "AgentState":
        return self.model_copy(update={"tool_chain_log": self.tool_chain_log + [msg]})

    def log_reasoning(self, msg: str) -> "AgentState":
        return self.model_copy(update={"reasoning_log": self.reasoning_log + [msg]})

    def append_scratchpad(self, step: ReActStep) -> "AgentState":
        return self.model_copy(update={"scratchpad": self.scratchpad + [step]})

    def reset_for_retry(self) -> "AgentState":
        return self.model_copy(update={
            "route":            None,
            "phase":            "seed",
            "ids_from_vector":  [],
            "enriched_data":    [],
            "curated_context":  [],
            "assembly_draft":   "",
            "final_answer":     "",
            "graph_intent":     None,
            "is_hallucinating": False,
            "violations":       [],
            "fallback_reason":  None,
            "needs_more_info":  False,
            "additional_query": None,
            "scratchpad":       [],
            "next_action":      None,
            "react_step":       0,
            "is_finished":      False,
            "error":            None,
            # token_usage intentionally NOT reset — accumulate across retries
        })


# ══════════════════════════════════════════════════════════════
# 7. PARSE HELPERS
# ══════════════════════════════════════════════════════════════

def parse_book_node(raw: dict) -> BookNode:
    """
    Parse dict mentah dari Graph/Vector tool → BookNode.

    Menangani dua format:
    A) Flat dict (Vector DB): {"id": "...", "title": "...", "score": 0.9}
    B) Nested dict (Neo4j):   {"book": {...}, "authors": [...], ...}
    """
    if "book" in raw and isinstance(raw["book"], dict):
        book_props = raw["book"]
    else:
        book_props = raw

    meta: dict = book_props.get("metadata") or {}
    merged = {**meta, **book_props}

    return BookNode(
        book_id       = merged.get("book_id") or merged.get("id", ""),
        title         = merged.get("title", ""),
        isbn_13       = merged.get("isbn_13") or merged.get("isbn"),
        pub_year      = merged.get("pub_year") or merged.get("year"),
        total_pages   = merged.get("total_pages"),
        abstract_clean = merged.get("abstract_clean") or merged.get("description"),
        is_fiction    = bool(merged.get("is_fiction", False)),
        cover_url     = merged.get("cover_url"),
        ddc_class     = merged.get("ddc_class"),
        language      = merged.get("language"),
        edisi         = merged.get("edisi"),
        relevance_score = merged.get("relevance_score") or merged.get("score", 0.0),

        authors    = [AuthorNode(**a) if isinstance(a, dict) else a
                      for a in (raw.get("authors") or [])
                      if (a.get("name") if isinstance(a, dict) else getattr(a, "name", None)) is not None],
        publisher  = (PublisherNode(**raw["publisher"])
                      if isinstance(raw.get("publisher"), dict) and raw["publisher"].get("name")
                      else None),
        categories = [CategoryNode(**c) if isinstance(c, dict) else c
                      for c in (raw.get("categories") or [])
                      if (c.get("name") if isinstance(c, dict) else getattr(c, "name", None)) is not None],
        branches   = [BranchNode(**b) if isinstance(b, dict) else b
                      for b in (raw.get("branches") or [])
                      if (b.get("name") if isinstance(b, dict) else getattr(b, "name", None)) is not None],
        vibes      = [VibeNode(**v) if isinstance(v, dict) else v
                      for v in (raw.get("vibes") or [])
                      if (v.get("name") if isinstance(v, dict) else getattr(v, "name", None)) is not None],
        settings   = [SettingNode(**s) if isinstance(s, dict) else s
                      for s in (raw.get("settings") or [])
                      if (s.get("name") if isinstance(s, dict) else getattr(s, "name", None)) is not None],
        characters = [CharacterNode(**c) if isinstance(c, dict) else c
                      for c in (raw.get("characters") or [])
                      if (c.get("name") if isinstance(c, dict) else getattr(c, "name", None)) is not None],
    )


def parse_book_nodes(raw_list: list[dict]) -> list[BookNode]:
    """Parse list raw dicts → list[BookNode]. Skip yang gagal parse."""
    import logging
    log = logging.getLogger(__name__)
    result: list[BookNode] = []
    for raw in raw_list:
        try:
            result.append(parse_book_node(raw))
        except Exception as exc:
            log.warning("Gagal parse BookNode %s: %s", raw.get("id", raw.get("book_id", "?")), exc)
    return result


# Jumlah judul final yang disajikan sebagai rekomendasi ke pengguna (kartu UI +
# teks jawaban Responder), SERAGAM lintas keenam pipeline agar perbandingan
# penyajian/judge kualitatif adil dan UX konsisten. Satu sumber-kebenaran supaya
# tidak drift lagi (dulu: Standard/CoT=5, SSG/PureReAct/Act-only=8, Planned=15).
# Catatan: Precision@3/@5 hanya melihat top-3/5 sehingga tak terpengaruh nilai ini;
# yang terdampak adalah panjang jawaban akhir + Answer Contains/Fase-2.
RECOMMEND_TOP_K = 15


def recommendation_order(books: list[BookNode]) -> list[BookNode]:
    """Urutkan daftar buku terkurasi untuk tampilan & skor: yang TERSEDIA dulu,
    urutan masukan dipertahankan dalam tiap tier (diasumsikan sudah "paling
    relevan dulu"), lalu stamp `relevance_score` menurun (rank-decay) supaya
    kartu di UI punya angka "paling direkomendasikan" yang bermakna & menurun.

    Dipakai BERSAMA semua arm (Search-Space-Gated, Planned, Pure ReAct,
    Act-only) supaya urutan curated_context (UI + Precision@K) konsisten —
    arm berbeda hanya pada CARA membangun pool, bukan cara mengurutkan hasil.
    `sorted` stabil, jadi urutan masukan terjaga di dalam tier ketersediaan.
    """
    ordered = sorted(books, key=lambda b: (not b.is_available,))
    n = len(ordered)
    if not n:
        return []
    return [
        b.model_copy(update={"relevance_score": round(1.0 - i / n, 4)})
        for i, b in enumerate(ordered)
    ]


# Backward compat
parse_book  = parse_book_node
parse_books = parse_book_nodes
