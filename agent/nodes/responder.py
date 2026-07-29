"""
Node 3/3 — Responder (Synthesis + Self-Audit)
──────────────────────────────────────────────
Menggabungkan tugas yang dulu dikerjakan tiga node:
  • content_assembly  → susunan narasi
  • generation        → finalisasi gaya bahasa
  • policy_loop       → audit anti-halusinasi (5 dimensi)

Dijalankan SETELAH ReAct loop selesai (state.is_finished == True).
Output: state.final_answer (sudah lulus audit), state.violations.

Inline audit (no LLM) — tetap multi-dimensi:
  1. hallucinated_title — judul disebut tapi tidak ada di curated_context
  2. wrong_author       — nama penulis tidak match BookNode.authors
  3. wrong_branch       — klaim ketersediaan tidak match BookNode.branches
  4. wrong_vibe         — klaim nuansa tidak ada di BookNode.vibes
  5. empty_answer       — final_answer kosong / terlalu pendek
"""

from __future__ import annotations

import logging
import os
import re

from agent.core.state import AgentState, BookNode, PolicyViolation
from agent.services.llm_services import llm
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# PROMPT
# ══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are a friendly, articulate public-library book recommender.
Write the final answer for a visitor based ONLY on the OFFICIAL CONTEXT below. The
context has already been curated by the agent — it is NOT your job to re-validate it.

LANGUAGE: these instructions are in English, but your OUTPUT MUST be written in
Bahasa Indonesia (the visitors and the catalog are Indonesian). Tone: warm and
professional. Do NOT use ANY emoji.

ABSOLUTE RULES:
1. Use ONLY facts that appear in the CONTEXT. Never add prices, external ratings,
   or any detail outside the context.
2. Recommend ONLY book titles that appear EXACTLY in the OFFICIAL CONTEXT below.
   Never invent, translate, or add a title that is not in the list — even if it
   sounds relevant. If the context has only 1 book, mention just that 1 book; do
   NOT pad it with invented titles.
3. EXPLAIN WHY each highlighted book is recommended. For every book you mention,
   give a short, concrete reason that ties the book's ACTUAL attributes shown in
   the context — category, vibe, setting, character, author, DDC, language, year,
   availability, and the synopsis — to what the user asked for. Prefer the
   attribute the user's request is actually about (e.g. for a DDC/language/author
   query, justify with that field). Never just list titles — the value is the
   justification. Ground every reason ONLY in the context; do NOT invent
   motivations the data does not support.
4. State branch availability explicitly when present — it matters to the visitor.
5. Do NOT attribute a vibe that is NOT in the book's data. If a book only has vibe
   "romance", do not call it "petualangan" or any other vibe.
6. Highlight AS MANY genuinely-fitting books as the context offers — aim for the
   top 6–8 best matches, or ALL of them if the context has fewer. The books are
   already ordered most-relevant-first, so cover the strong matches broadly rather
   than stopping at two or three. BUT keep a quality bar: prioritize the most
   relevant, and do NOT pad with weak/irrelevant matches just to reach a number.
   Each highlighted book still needs its own concrete, grounded reason (Rule 3).

OUTPUT FORMAT — Bahasa Indonesia, warm and natural (like a friendly librarian
chatting with a visitor), written as CLEAN Markdown that WILL be rendered:
- NO emoji anywhere.
- Open with a warm, natural intro (1–2 sentences) that connects to what the user
  asked. Vary it — do NOT reuse a fixed template like "Berikut rekomendasi...".
- Then a Markdown bullet list of the best-fitting books (aim for 6–8, or all if
  fewer — see Rule 6): one "- " item per book, the TITLE in **bold**, followed by
  a natural, specific reason it fits — grounded in that book's attributes/synopsis.
  Phrase each reason differently; do NOT repeat the same sentence pattern for every
  book, and let the length vary a little.
- Close with a short, friendly line (e.g. invite them to refine the request).
- Use **bold** for titles only. NO headings (#), NO tables, NO JSON, NO emoji."""


_USER_TEMPLATE = """USER REQUEST:
"{query}"

OFFICIAL CONTEXT ({n} books — do NOT go outside this):
{context_lines}

Write the final answer in Bahasa Indonesia — warm, natural, and grounded (follow
the OUTPUT FORMAT): a friendly intro, then a Markdown bullet list of the best-fitting
books (aim for 6–8, or all if the context has fewer — prioritize the most relevant,
never pad with weak matches), each item = **book title** + a natural reason WHY it
fits (vary the phrasing), referencing that book's attributes from the context above.
No emoji."""


# ══════════════════════════════════════════════════════════════
# CONTEXT BUILDER
# ══════════════════════════════════════════════════════════════

def _build_rich_context(books: list[BookNode]) -> str:
    """Render curated_context (hasil retrieval) jadi teks grounding untuk
    responder. Menyertakan SEMUA atribut yang bisa jadi dasar "kenapa
    direkomendasikan" — kategori/vibe/latar/tokoh + DDC/bahasa/tahun +
    sinopsis (dipotong) + ketersediaan — supaya model bisa beralasan akurat
    untuk tipe query apa pun, bukan hanya vibe/setting/category."""
    lines = []
    for b in books:
        authors  = ", ".join(b.author_names) or "Unknown"
        cats     = ", ".join(c.name for c in b.categories) or "-"
        vibes    = ", ".join(b.vibe_names) or "-"
        settings = ", ".join(b.setting_names) or "-"
        chars    = ", ".join(c.name for c in b.characters)
        avail = (
            f"Tersedia di: {', '.join(b.available_at)}"
            if b.is_available else "Tidak tersedia di cabang mana pun"
        )

        attr_line = f"  Kategori: {cats} | Vibe: {vibes} | Latar: {settings}"
        if chars:
            attr_line += f" | Tokoh: {chars}"

        meta_bits: list[str] = []
        if b.ddc_class:
            meta_bits.append(f"DDC {b.ddc_class}")
        if b.language:
            meta_bits.append(f"Bahasa {b.language}")
        if b.publisher and b.publisher.name:
            pub = b.publisher.name + (f" ({b.publisher.city})" if b.publisher.city else "")
            meta_bits.append(f"Penerbit {pub}")
        if b.pub_year:
            meta_bits.append(f"Terbit {b.pub_year}")

        parts = [f'• [{b.book_id}] "{b.title}" oleh {authors}', attr_line]
        if meta_bits:
            parts.append("  " + " | ".join(meta_bits))
        parts.append(f"  {avail}")
        if b.abstract_clean:
            syn = " ".join(b.abstract_clean.split())
            if len(syn) > 240:
                syn = syn[:240].rstrip() + "…"
            parts.append(f"  Sinopsis: {syn}")

        lines.append("\n".join(parts))
    return "\n\n".join(lines)


# ══════════════════════════════════════════════════════════════
# AUDIT (deterministic, no LLM)
# ══════════════════════════════════════════════════════════════

def _extract_quoted_titles(text: str) -> list[str]:
    return re.findall(r'["“”]([^"]{3,80})["“”]', text)


def _extract_author_mentions(text: str) -> list[str]:
    matches = re.findall(r'(?:oleh|karya|penulis)\s+([A-Z][a-zA-Z\s]{2,40})', text, re.I)
    return [re.sub(r'[.,;]+$', '', m).strip() for m in matches]


def _audit_titles(mentioned_titles: list[str], context: list[BookNode]) -> list[PolicyViolation]:
    known = {b.title.lower() for b in context}
    out: list[PolicyViolation] = []
    for t in mentioned_titles:
        tl = t.lower()
        if not any(tl in kt or kt in tl for kt in known):
            out.append(PolicyViolation(
                violation_type="hallucinated_title",
                detail=f'Judul "{t}" tidak ada di curated_context.',
                offending_text=t,
            ))
    return out


def _audit_authors(mentioned_authors: list[str], context: list[BookNode]) -> list[PolicyViolation]:
    all_authors = {a.name.lower() for b in context for a in b.authors}
    out: list[PolicyViolation] = []
    for au in mentioned_authors:
        al = au.lower()
        if not any(al in ka or ka in al for ka in all_authors):
            out.append(PolicyViolation(
                violation_type="wrong_author",
                detail=f'Penulis "{au}" tidak ada di curated_context.',
                offending_text=au,
            ))
    return out


def _audit_branch_claims(answer: str, context: list[BookNode]) -> list[PolicyViolation]:
    out: list[PolicyViolation] = []
    a_low = answer.lower()
    for b in context:
        tl = b.title.lower()
        if tl not in a_low:
            continue
        idx = a_low.find(tl)
        window = a_low[max(0, idx - 80): idx + 250]
        claims_avail = any(k in window for k in ["tersedia", "✅", "bisa dipinjam", "ada di"])
        claims_habis = any(k in window for k in ["tidak tersedia", "habis", "❌", "kosong"])
        if claims_avail and not b.is_available:
            out.append(PolicyViolation(
                violation_type="wrong_branch",
                detail=f'"{b.title}" diklaim tersedia tapi branches kosong.',
                offending_text=b.title,
            ))
        elif claims_habis and b.is_available:
            out.append(PolicyViolation(
                violation_type="wrong_branch",
                detail=f'"{b.title}" diklaim tidak tersedia tapi ada di {b.available_at}.',
                offending_text=b.title,
            ))
    return out


_VIBE_VOCAB = [
    "romance", "misteri", "thriller", "horor", "petualangan",
    "komedi", "inspiratif", "motivasi", "dark", "spiritual",
]


def _audit_vibe_claims(answer: str, context: list[BookNode]) -> list[PolicyViolation]:
    out: list[PolicyViolation] = []
    a_low = answer.lower()
    for b in context:
        tl = b.title.lower()
        if tl not in a_low or not b.vibes:
            continue
        book_vibes = {v.name.lower() for v in b.vibes}
        idx = a_low.find(tl)
        window = a_low[max(0, idx - 40): idx + 300]
        for kw in _VIBE_VOCAB:
            if kw in window and not any(kw in bv for bv in book_vibes):
                out.append(PolicyViolation(
                    violation_type="wrong_vibe",
                    detail=f'"{b.title}" diklaim ber-vibe "{kw}" tapi data: {sorted(book_vibes)}.',
                    offending_text=kw,
                ))
                break
    return out


def _run_audit(answer: str, context: list[BookNode]) -> list[PolicyViolation]:
    violations: list[PolicyViolation] = []
    violations += _audit_titles(_extract_quoted_titles(answer), context)
    violations += _audit_authors(_extract_author_mentions(answer), context)
    violations += _audit_branch_claims(answer, context)
    violations += _audit_vibe_claims(answer, context)
    return violations


# ══════════════════════════════════════════════════════════════
# LLM CALL
# ══════════════════════════════════════════════════════════════

def _generate(query: str, books: list[BookNode], state: AgentState) -> tuple[str, AgentState]:
    user = _USER_TEMPLATE.format(
        query=query, n=len(books), context_lines=_build_rich_context(books),
    )
    resp = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user),
    ])
    updated_state = state.model_copy(update={"token_usage": state.token_usage.add(resp)})
    return (getattr(resp, "content", "") or "").strip(), updated_state


# ══════════════════════════════════════════════════════════════
# NODE
# ══════════════════════════════════════════════════════════════

def responder_node(state: AgentState, *, self_correct: bool = True) -> AgentState:
    """
    Susun final_answer + jalankan audit.

    `self_correct`: kalau True (default), retry sekali dengan instruksi
    eksplisit saat audit gagal — perilaku asli, dipakai workflow.py.
    Kalau False, audit tetap jalan & violations tetap dicatat untuk
    observability, tapi TIDAK ada LLM call kedua — dipakai
    `workflow_pure_react.py` (lihat docs/catatan_riset.md § 4: validator/
    self-correct retry terbukti costly-low-yield di kedua proyek, jadi
    ablation ini sengaja menghilangkannya buat ngukur trade-off-nya).

    Override global: env `DISABLE_SELF_CORRECT=1` memaksa `self_correct=False`
    untuk SEMUA arm tanpa mengedit tiap workflow — dipakai run ablasi audit
    on/off (catatan_riset.md § 4.1). Audit deterministik (`_run_audit`) TETAP
    jalan & violations tetap dicatat; yang dimatikan hanya LLM retry-nya.
    """
    if os.getenv("DISABLE_SELF_CORRECT", "").strip().lower() in ("1", "true", "yes", "on"):
        self_correct = False

    books = state.curated_context

    if not books:
        msg = "Belum menemukan buku yang sesuai dengan permintaan kamu. Coba pertanyaan yang lebih spesifik atau sebutkan vibe/setting yang diinginkan."
        return state.model_copy(update={
            "final_answer":   msg,
            "is_hallucinating": False,
            "tool_chain_log": state.tool_chain_log + ["responder → curated_context kosong"],
            "error":          None,
        })

    try:
        answer, state = _generate(state.query, books, state)
    except Exception as exc:
        logger.exception("Responder LLM error: %s", exc)
        return state.model_copy(update={
            "final_answer": "Terjadi kesalahan saat menyusun jawaban final.",
            "error": f"Responder error: {exc}",
        })

    violations = _run_audit(answer, books) if answer else [
        PolicyViolation(violation_type="empty_answer", detail="final_answer kosong."),
    ]

    if violations and self_correct:
        # Self-correct sekali: minta ulang dengan instruksi eksplisit
        logger.warning(
            "Responder audit GAGAL (%d violations) — self-correct.", len(violations),
        )
        violation_summary = "; ".join(str(v) for v in violations[:5])
        correction_user = (
            _USER_TEMPLATE.format(
                query=state.query, n=len(books),
                context_lines=_build_rich_context(books),
            )
            + f"\n\nYOUR PREVIOUS DRAFT FAILED THE AUDIT: {violation_summary}\n"
              "Rewrite it in Bahasa Indonesia WITHOUT any claim that is not in the "
              "CONTEXT, and keep a concrete why-recommended reason for each book."
        )
        try:
            correction_resp = llm.invoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=correction_user),
            ])
            state = state.model_copy(update={"token_usage": state.token_usage.add(correction_resp)})
            raw_content = getattr(correction_resp, "content", "")
            if isinstance(raw_content, list):
                answer = " ".join(str(item) for item in raw_content).strip()
            else:
                answer = (raw_content or "").strip()
            violations = _run_audit(answer, books)
        except Exception as exc:
            logger.exception("Responder retry error: %s", exc)

    is_hallucinating = bool(violations)
    summary = "; ".join(str(v) for v in violations) if violations else None

    if is_hallucinating:
        if self_correct:
            logger.warning("Responder: %d violations bertahan setelah self-correct.", len(violations))
        else:
            logger.warning("Responder: %d violations (self-correct off, tidak ada retry).", len(violations))
    else:
        logger.info("Responder ✅ audit lolos.")

    return state.model_copy(update={
        "final_answer":     answer,
        "assembly_draft":   answer,        # untuk debug pane
        "is_hallucinating": is_hallucinating,
        "violations":       violations,
        "fallback_reason":  summary,
        "tool_chain_log":   state.tool_chain_log + [
            f"responder → {len(answer)} chars, "
            + (
                f"GAGAL {len(violations)} viol"
                + (" (self-correct off)" if is_hallucinating and not self_correct else "")
                if is_hallucinating else "audit lolos"
            )
        ],
        "reasoning_log":    state.reasoning_log + (
            [f"audit gagal: {summary}"] if is_hallucinating else ["audit lolos (5 dimensi)"]
        ),
        "error":            None,
    })
