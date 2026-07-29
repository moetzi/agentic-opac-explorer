"""
evaluation/run_comparative_evaluation.py — Comparative Evaluation Runner
─────────────────────────────────────────────────────────────────────────
Phase 1 of the two-phase evaluation workflow for the Agentic GraphRAG
book recommendation system.

Menjalankan 30 kueri ground truth pada pipeline berikut:
  1. Standard RAG         (single-hop vector + generate)
  2. Agentic GraphRAG     dengan Llama 3.1 8B
  3. Agentic GraphRAG     dengan Qwen 2.5 7B

Arm ablasi tambahan — OPT-IN saja (tidak ikut "all", pass eksplisit lewat
--pipelines), membentuk grid ala paper ReAct (reason-only / act-only / both):
  4. CoT-RAG              (retrieval Standard RAG + chain-of-thought generate)
  5. Pure ReAct           (full-autonomy: reasoning + acting, flat action space)
  6. Act-only             (Pure ReAct tanpa field "thought" — acting saja)

6-Metric Hybrid Framework
─────────────────────────
Metrik yang dihitung per-kueri:

  ┌─ Retrieval ─────────────────────────────────────────────────────┐
  │  precision@K     : |retrieved ∩ expected| / K                   │
  └─────────────────────────────────────────────────────────────────┘
  ┌─ Generation (offline proxy) ────────────────────────────────────┐
  │  answer_contains : fraksi keyword expected yang ada di jawaban  │
  │  (full RAGAS Faithfulness & Answer Relevance dijalankan         │
  │   terpisah di Phase 2: ragas_evaluation.py)                     │
  └─────────────────────────────────────────────────────────────────┘
  ┌─ Operational Agent Metrics ─────────────────────────────────────┐
  │  latency_s       : wall-clock time per query                    │
  │  token_usage      : input/output/total tokens dari LLM          │
  │  tool_set_match   : |called ∩ expected| / |expected|  (NEW)     │
  └─────────────────────────────────────────────────────────────────┘

Output:
  evaluation/hasil_eval/eval_results_standard_<timestamp>.json
  evaluation/hasil_eval/eval_results_agentic_llama_<timestamp>.json
  evaluation/hasil_eval/eval_results_agentic_qwen_<timestamp>.json

Phase 2 (RAGAS LLM-as-Judge):
  → python evaluation/ragas_evaluation.py [--use-groq]
  Consumes the JSON output above and adds Faithfulness + Answer Relevance.
"""

import gc
import json
import os
import sys
import time
import argparse
import torch
import importlib
from datetime import datetime
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

# Windows default console codepage (cp1252) can't encode the ✅/❌/─ characters below.
# Prefer calling TextIO.reconfigure when available, but access it via getattr to
# avoid static-analysis warnings about unknown attributes on sys.stdout.
reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(reconfigure):
    try:
        reconfigure(encoding="utf-8")
    except Exception:
        pass
else:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    except Exception:
        pass


# ── Imports from shared metrics module ────────────────────────────────────────

from evaluation.metrics import (
    precision_at_k,
    answer_contains_check,
    title_faithfulness,
    tool_set_match,
    extract_tools_used,
    count_destructive_filter_calls,
    build_contexts,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_CURRENT_OLLAMA_MODEL: str | None = None


def _unload_ollama_model(model_name: str) -> None:
    """
    Best-effort: evict `model_name` dari VRAM Ollama, supaya Llama dan Qwen
    gantian (satu model di VRAM dalam satu waktu) bukan numpuk berdua —
    penting di GPU remote yang VRAM-nya terbatas. Kegagalan di sini
    non-fatal; eval tetap lanjut, model lama paling cuma nunggu
    OLLAMA_KEEP_ALIVE habis sendiri.

    Sengaja HTTP request langsung ke OLLAMA_BASE_URL (bukan `ollama stop`
    CLI) — CLI itu pakai OLLAMA_HOST sendiri (default 127.0.0.1:11434) yang
    BISA BEDA dari OLLAMA_BASE_URL kalau Ollama-nya di GPU remote diakses
    lewat SSH tunnel ke port non-default (mis. 11450). CLI yang salah
    target = diam-diam nggak ngapa-ngapain, server remote tetap penuh.
    Request kosong (tanpa `prompt`) + `keep_alive: 0` ke /api/generate
    adalah cara resmi Ollama buat unload immediate.
    """
    base_url = os.getenv("OLLAMA_BASE_URL")
    if not base_url:
        return
    try:
        import requests
        requests.post(
            f"{base_url}/api/generate",
            json={"model": model_name, "keep_alive": 0},
            timeout=15,
        )
    except Exception as exc:
        print(f"  ⚠️  Tidak bisa unload model '{model_name}' dari {base_url}: {exc}")


def _set_ollama_model(model_name: str):
    """
    Override OLLAMA_MODEL env var dan benar-benar pindah model:

    1. Unload model SEBELUMNYA dari VRAM Ollama (best-effort) — biar Llama &
       Qwen gantian, tidak numpuk berdua di VRAM yang kecil.
    2. Reset lazy singleton di llm_services.py.
    3. Reload `agent.nodes.reasoner` & `agent.nodes.responder` — keduanya
       `from agent.services.llm_services import llm_json` / `llm` di waktu
       IMPORT MEREKA SENDIRI (binding statis, sekali jalan). Tanpa reload
       ini, mereka tetap pegang instance model LAMA walau env var & cache di
       llm_services.py sudah diganti — bug nyata yang sempat bikin pipeline
       "Agentic GraphRAG (Qwen)" diam-diam tetap jalan pakai Llama (lihat
       docs/catatan_riset.md § 8). Modul lain (workflow.py,
       workflow_pure_react.py, standard_rag.py) TIDAK perlu direload: mereka
       cuma pegang reference ke fungsi reasoner_node/responder_node, dan
       `__globals__` fungsi itu live-link ke namespace reasoner.py/
       responder.py — otomatis ikut update walau reload bikin ulang object
       fungsinya.
    4. gc.collect() + bersihkan cache CUDA sisi Python, melengkapi unload
       sisi Ollama di atas.
    """
    global _CURRENT_OLLAMA_MODEL
    if _CURRENT_OLLAMA_MODEL and _CURRENT_OLLAMA_MODEL != model_name:
        _unload_ollama_model(_CURRENT_OLLAMA_MODEL)
    _CURRENT_OLLAMA_MODEL = model_name

    os.environ["OLLAMA_MODEL"] = model_name

    try:
        import agent.services.llm_services as llm_svc
        llm_svc._llm_instance = None
        llm_svc._llm_json_instance = None

        for mod_name in ("agent.nodes.reasoner", "agent.nodes.responder"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                importlib.reload(mod)
    except Exception as exc:
        print(f"  ⚠️  Gagal reset/reload LLM singleton untuk '{model_name}': {exc}")

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


K_VALUES = (3, 5)


def _expected_titles(gt: dict) -> list[str]:
    """Returns expected titles lowercased for matching."""
    return [t.lower() for t in gt.get("expected_titles", [])]


def evaluate_single(gt: dict, pipeline_func: Callable) -> dict:
    """
    Jalankan satu kueri dan hitung semua offline metrics.

    Metrics computed per query:
      - precision_at_3/5         (Retrieval)
      - answer_contains          (Generation proxy)
      - elapsed_seconds          (Operational: Latency)
      - token_usage              (Operational: Token Cost)
      - tool_set_match           (Operational: Tool Set Match)
      - destructive_filter_calls (Operational: hallucinated filter args that
                                   would've wiped the pool — see
                                   evaluation/metrics.py::count_destructive_filter_calls.
                                   Computed for EVERY query, unlike
                                   tool_set_match which needs expected_tools)
      - tools_used               (diagnostic — list of tools actually called)
    """
    query = gt["query"]
    start = time.time()
    try:
        state = pipeline_func(query)
        elapsed = round(time.time() - start, 2)
    except Exception as exc:
        return {
            "id": gt["id"], "query": query,
            "query_type": gt.get("query_type"), "hop_count": gt.get("hop_count"),
            "error": str(exc), "elapsed_seconds": round(time.time() - start, 2),
            "answer": None, "contexts": [], "curated_titles": [],
            **{f"precision_at_{k}": None for k in K_VALUES},
            "answer_contains_score": 0.0,
            "title_faithfulness": None,
            "tool_set_match": None, "tools_used": [], "destructive_filter_calls": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }

    curated_titles_lower = [b.title.lower() for b in state.curated_context]
    contexts = build_contexts(state)
    expected_titles = _expected_titles(gt)
    precisions = {f"precision_at_{k}": precision_at_k(curated_titles_lower, expected_titles, k=k) for k in K_VALUES}
    ac_score = answer_contains_check(state.final_answer or "", gt.get("expected_answer_contains", []))
    faithfulness = title_faithfulness(
        state.final_answer or "",
        [b.title for b in state.curated_context],
        query=query,
    )

    # ── Operational: Tool Set Match + destructive filter diagnostic ────
    tsm = tool_set_match(state.tool_chain_log, gt.get("expected_tools", []))
    tools_used = extract_tools_used(state.tool_chain_log)
    destructive_filter_calls = count_destructive_filter_calls(state.tool_chain_log)

    return {
        "id": gt["id"],
        "query": query,
        "query_type": gt.get("query_type"),
        "hop_count": gt.get("hop_count"),
        "elapsed_seconds": elapsed,
        "error": state.error,
        "answer": state.final_answer,
        "contexts": contexts,
        "curated_titles": [b.title for b in state.curated_context],
        **precisions,
        "answer_contains_score": ac_score,
        "title_faithfulness": faithfulness if faithfulness >= 0 else None,
        "tool_set_match": tsm if tsm >= 0 else None,
        "tools_used": tools_used,
        "destructive_filter_calls": destructive_filter_calls,
        "reference_answer": gt.get("reference_answer", ""),
        "token_usage": {
            "input_tokens": state.token_usage.input_tokens,
            "output_tokens": state.token_usage.output_tokens,
            "total_tokens": state.token_usage.total_tokens,
        },
    }


def _aggregate_group(rows: list[dict]) -> dict:
    """
    Hitung metrik agregat untuk satu kelompok result rows (per query_type /
    per hop_count). Semantik sama dengan agregat global di run_pipeline():
    error rows dikecualikan dari metrik kualitas tapi tetap dihitung di
    latency & error_count; precision -1/None dan TSM None dianggap
    tidak-terevaluasi (bukan nol).
    """
    valid = [r for r in rows if not r["error"]]
    out: dict = {"n": len(rows), "error_count": len(rows) - len(valid)}
    for k in K_VALUES:
        field = f"precision_at_{k}"
        evaluable = [r[field] for r in valid if r.get(field) is not None and r[field] >= 0]
        out[f"avg_{field}"] = round(sum(evaluable) / len(evaluable), 4) if evaluable else None
    out["avg_answer_contains"] = (
        round(sum(r["answer_contains_score"] for r in valid) / len(valid), 4) if valid else None
    )
    evaluable_faith = [r["title_faithfulness"] for r in valid if r.get("title_faithfulness") is not None]
    out["avg_title_faithfulness"] = (
        round(sum(evaluable_faith) / len(evaluable_faith), 4) if evaluable_faith else None
    )
    evaluable_tsm = [r["tool_set_match"] for r in valid if r.get("tool_set_match") is not None]
    out["avg_tool_set_match"] = round(sum(evaluable_tsm) / len(evaluable_tsm), 4) if evaluable_tsm else None
    out["avg_latency_seconds"] = round(sum(r["elapsed_seconds"] for r in rows) / len(rows), 2) if rows else None
    out["total_destructive_filter_calls"] = sum(r.get("destructive_filter_calls", 0) for r in rows)
    return out


def _group_by(results: list[dict], key: str) -> dict:
    """Kelompokkan result rows per nilai `key` (query_type / hop_count) → agregat."""
    groups: dict = {}
    for r in results:
        groups.setdefault(str(r.get(key) if r.get(key) is not None else "unknown"), []).append(r)
    return {k: _aggregate_group(v) for k, v in sorted(groups.items())}


def run_pipeline(
    pipeline_name: str,
    pipeline_func: Callable,
    ground_truth: list[dict],
    out_path: str,
    model_label: str,
):
    print(f"\n{'─'*70}")
    print(f"  Pipeline : {pipeline_name} [{model_label}]")
    print(f"  Queries  : {len(ground_truth)}  |  Output: {os.path.basename(out_path)}")
    print(f"{'─'*70}")

    results = []
    for i, gt in enumerate(ground_truth, 1):
        label = f"[{i:2d}/{len(ground_truth)}]"
        print(f"{label} {gt['id']} — {gt['query'][:55]}...", end=" ", flush=True)
        res = evaluate_single(gt, pipeline_func)
        results.append(res)
        if res["error"]:
            print(f"❌ ({res['elapsed_seconds']}s)")
        else:
            p_strs = " ".join(
                f"P@{k}={res[f'precision_at_{k}']:.2f}" if res[f"precision_at_{k}"] >= 0 else f"P@{k}=N/A"
                for k in K_VALUES
            )
            tsm_str = f"TSM={res['tool_set_match']:.2f}" if res["tool_set_match"] is not None else "TSM=N/A"
            faith_str = f"F={res['title_faithfulness']:.2f}" if res["title_faithfulness"] is not None else "F=N/A"
            df_str = f"  ⚠️DF={res['destructive_filter_calls']}" if res["destructive_filter_calls"] else ""
            print(f"✅ {p_strs}  AC={res['answer_contains_score']:.2f}  {faith_str}  {tsm_str}{df_str}  ({res['elapsed_seconds']}s)")

        # ── VRAM cleanup: free GPU memory between queries ──────────────
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ── Aggregate offline metrics ─────────────────────────────────────
    valid = [r for r in results if not r["error"]]
    avg_precisions = {}
    for k in K_VALUES:
        field = f"precision_at_{k}"
        evaluable = [r[field] for r in valid if r[field] is not None and r[field] >= 0]
        avg_precisions[f"avg_{field}"] = round(sum(evaluable) / len(evaluable), 4) if evaluable else None

    evaluable_tsm = [r["tool_set_match"] for r in valid if r["tool_set_match"] is not None]

    evaluable_faith = [r["title_faithfulness"] for r in valid if r.get("title_faithfulness") is not None]

    avg_ac = round(sum(r["answer_contains_score"] for r in valid) / len(valid), 4) if valid else None
    avg_lat = round(sum(r["elapsed_seconds"] for r in results) / len(results), 2)
    avg_tsm = round(sum(evaluable_tsm) / len(evaluable_tsm), 4) if evaluable_tsm else None
    avg_faith = round(sum(evaluable_faith) / len(evaluable_faith), 4) if evaluable_faith else None

    # Destructive filter calls — computed for every query regardless of
    # expected_tools, so it also catches the thematic/vibe queries that
    # tool_set_match can't evaluate (expected_tools empty → TSM=-1.0/None).
    total_destructive = sum(r.get("destructive_filter_calls", 0) for r in results)
    queries_with_destructive = sum(1 for r in results if r.get("destructive_filter_calls", 0) > 0)

    # Token totals
    total_input  = sum(r["token_usage"]["input_tokens"] for r in results)
    total_output = sum(r["token_usage"]["output_tokens"] for r in results)
    total_tokens = sum(r["token_usage"]["total_tokens"] for r in results)

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "pipeline": pipeline_name,
        "model": model_label,
        "total_queries": len(ground_truth),
        "k_values": list(K_VALUES),
        "aggregate": {
            **avg_precisions,
            "avg_answer_contains": avg_ac,
            "avg_title_faithfulness": avg_faith,
            "avg_latency_seconds": avg_lat,
            "avg_tool_set_match": avg_tsm,
            "total_destructive_filter_calls": total_destructive,
            "queries_with_destructive_filter": queries_with_destructive,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "avg_tokens_per_query": round(total_tokens / len(results)) if results else 0,
            "error_count": len(results) - len(valid),
        },
        # Breakdown per tipe query & per hop count — dipakai untuk analisis
        # "bagaimana arm X beradaptasi terhadap tipe input berbeda"
        # (evaluation/analyze_by_query_type.py juga bisa menghitung ini
        # post-hoc dari result rows untuk file lama yang belum punya field ini).
        "by_query_type": _group_by(results, "query_type"),
        "by_hop_count": _group_by(results, "hop_count"),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"metadata": metadata, "results": results}, f, ensure_ascii=False, indent=2)

    p_summary = "  ".join(f"P@{k}={avg_precisions[f'avg_precision_at_{k}']}" for k in K_VALUES)
    df_summary = f"  DestructiveFilters={total_destructive} ({queries_with_destructive}/{len(results)} queries)" if total_destructive else ""
    print(f"\n  ✓ Avg {p_summary}  AC={avg_ac}  Faith={avg_faith}  TSM={avg_tsm}  Lat={avg_lat}s{df_summary}  → {os.path.basename(out_path)}")
    return metadata


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Comparative Evaluation: GraphRAG vs Standard RAG")
    parser.add_argument("--limit", type=int, default=0, help="Limit queries per pipeline (0=all)")
    parser.add_argument("--start", type=int, default=0, help="Start from query index")
    parser.add_argument(
        "--pipelines", nargs="+",
        choices=["standard", "cot", "llama", "qwen", "pure_react", "act_only", "planned", "all"],
        default=["all"],
        help="Which pipelines to run (default: all — NOTE: the ablation arms "
             "'cot', 'pure_react', 'act_only', and 'planned' are opt-in only, "
             "not part of 'all'; pass them explicitly)",
    )
    parser.add_argument(
        "--llama-model", default=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        help="Ollama model tag for Llama pipeline",
    )
    parser.add_argument(
        "--qwen-model", default="qwen2.5:7b",
        help="Ollama model tag for Qwen pipeline",
    )
    parser.add_argument(
        "--pure-react-model", default=None,
        help="Ollama model tag for the Pure ReAct ablation (default: --llama-model)",
    )
    parser.add_argument(
        "--cot-model", default=None,
        help="Ollama model tag for the CoT-RAG ablation (default: --llama-model)",
    )
    parser.add_argument(
        "--act-only-model", default=None,
        help="Ollama model tag for the Act-only ablation (default: --llama-model)",
    )
    parser.add_argument(
        "--planned-model", default=None,
        help="Ollama model tag for the single-shot Planned ablation (default: --llama-model)",
    )
    parser.add_argument(
        "--no-self-correct", action="store_true",
        help="Matikan responder self-correct untuk SEMUA arm (A/B audit on/off): "
             "set env DISABLE_SELF_CORRECT=1 + tandai file output dengan suffix "
             "'_noaudit'. Audit deterministik tetap jalan, hanya LLM retry-nya mati.",
    )
    args = parser.parse_args()

    if args.no_self_correct:
        os.environ["DISABLE_SELF_CORRECT"] = "1"

    eval_dir = os.path.dirname(os.path.abspath(__file__))
    gt_path = os.path.join(eval_dir, "ground_truth.json")
    
    hasil_dir = os.path.join(eval_dir, "hasil_eval")
    os.makedirs(hasil_dir, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S") + ("_noaudit" if args.no_self_correct else "")

    with open(gt_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    if args.start > 0:
        ground_truth = ground_truth[args.start:]
    if args.limit > 0:
        ground_truth = ground_truth[:args.limit]

    run_set = set(args.pipelines)
    run_all = "all" in run_set

    # Load SentenceTransformer SEKALI di sini, sebelum pipeline apapun jalan —
    # get_embedding_model() di-cache (@lru_cache(maxsize=1)) jadi panggilan
    # berikutnya dari VectorSearchTool manapun (Standard RAG, vector
    # front-door, vector_search tool di pure_react) selalu reuse model yang
    # sama, tidak pernah load ulang/alokasi VRAM baru. Eager di sini supaya
    # waktu load-nya jelas terlihat di awal, bukan numpuk diam-diam di tengah
    # query pertama pipeline manapun yang kebetulan duluan butuh dia.
    from agent.tools.vector_tool import get_embedding_model
    get_embedding_model()
    gc.collect()

    print("=" * 70)
    print("  COMPARATIVE EVALUATION")
    print(f"  Queries: {len(ground_truth)}  |  Precision@K: K={K_VALUES}")
    # Label by the CLI arg that sets each slot, not by an assumed model family —
    # --llama-model just defaults to OLLAMA_MODEL, so it can hold any tag.
    print(f"  Base model (--llama-model) : {args.llama_model}")
    print(f"  Alt  model (--qwen-model)  : {args.qwen_model}")
    # Per-arm overrides fall back to --llama-model; show them only when set so
    # the header never implies an arm ran on the base model when it didn't.
    for label, override in (
        ("Pure ReAct", args.pure_react_model),
        ("CoT-RAG", args.cot_model),
        ("Act-only", args.act_only_model),
        ("Planned", args.planned_model),
    ):
        if override:
            print(f"  Override: {label:<11}-> {override}")
    if args.no_self_correct:
        print("  Self-correct : OFF (DISABLE_SELF_CORRECT=1) — audit-off A/B, file bertag '_noaudit'")
    print("=" * 70)

    summaries = {}

    # ── 1. Standard RAG ──────────────────────────────────────────────────────
    if run_all or "standard" in run_set:
        _set_ollama_model(args.llama_model)
        from agent.core.standard_rag import run_standard_rag
        meta = run_pipeline(
            pipeline_name="Standard RAG",
            pipeline_func=run_standard_rag,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_standard_{timestamp_str}.json"),
            model_label=args.llama_model,
        )
        summaries["Standard RAG"] = meta["aggregate"]

    # ── 1b. CoT-RAG (reason-only ablation, opt-in only) ──────────────────────
    if "cot" in run_set:
        cot_model = args.cot_model or args.llama_model
        cot_slug = cot_model.split(":")[0].replace(".", "")
        _set_ollama_model(cot_model)
        from agent.core.standard_rag import run_standard_rag_cot
        meta = run_pipeline(
            pipeline_name="CoT-RAG",
            pipeline_func=run_standard_rag_cot,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_cot_rag_{cot_slug}_{timestamp_str}.json"),
            model_label=cot_model,
        )
        summaries[f"CoT-RAG ({cot_model})"] = meta["aggregate"]

    # ── 2. Agentic GraphRAG — Llama ──────────────────────────────────────────
    if run_all or "llama" in run_set:
        _set_ollama_model(args.llama_model)
        from agent.core.workflow import run_workflow
        meta = run_pipeline(
            pipeline_name="Agentic GraphRAG (Llama)",
            pipeline_func=run_workflow,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_agentic_llama_{timestamp_str}.json"),
            model_label=args.llama_model,
        )
        summaries[f"Agentic GraphRAG ({args.llama_model})"] = meta["aggregate"]

    # ── 3. Agentic GraphRAG — Qwen ───────────────────────────────────────────
    if run_all or "qwen" in run_set:
        _set_ollama_model(args.qwen_model)
        from agent.core.workflow import run_workflow
        meta = run_pipeline(
            pipeline_name="Agentic GraphRAG (Qwen)",
            pipeline_func=run_workflow,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_agentic_qwen_{timestamp_str}.json"),
            model_label=args.qwen_model,
        )
        summaries[f"Agentic GraphRAG ({args.qwen_model})"] = meta["aggregate"]

    # ── 4. Pure Full-Autonomy ReAct (ablation, opt-in only) ───────────────────
    if "pure_react" in run_set:
        pr_model = args.pure_react_model or args.llama_model
        pr_slug = pr_model.split(":")[0].replace(".", "")
        _set_ollama_model(pr_model)
        from agent.core.workflow_pure_react import run_workflow_pure_react
        meta = run_pipeline(
            pipeline_name="Agentic GraphRAG (Pure ReAct)",
            pipeline_func=run_workflow_pure_react,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_pure_react_{pr_slug}_{timestamp_str}.json"),
            model_label=pr_model,
        )
        summaries[f"Agentic GraphRAG Pure ReAct ({pr_model})"] = meta["aggregate"]

    # ── 5. Act-only ReAct (ablation, opt-in only) ─────────────────────────────
    if "act_only" in run_set:
        ao_model = args.act_only_model or args.llama_model
        ao_slug = ao_model.split(":")[0].replace(".", "")
        _set_ollama_model(ao_model)
        from agent.core.workflow_act_only import run_workflow_act_only
        meta = run_pipeline(
            pipeline_name="Agentic GraphRAG (Act-only)",
            pipeline_func=run_workflow_act_only,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_act_only_{ao_slug}_{timestamp_str}.json"),
            model_label=ao_model,
        )
        summaries[f"Agentic GraphRAG Act-only ({ao_model})"] = meta["aggregate"]

    # ── 6. Single-Shot Planned Retrieval (ablation, opt-in only) ──────────────
    if "planned" in run_set:
        pl_model = args.planned_model or args.llama_model
        pl_slug = pl_model.split(":")[0].replace(".", "")
        _set_ollama_model(pl_model)
        from agent.core.workflow_planned import run_workflow_planned
        meta = run_pipeline(
            pipeline_name="Agentic GraphRAG (Planned)",
            pipeline_func=run_workflow_planned,
            ground_truth=ground_truth,
            out_path=os.path.join(hasil_dir, f"eval_results_planned_{pl_slug}_{timestamp_str}.json"),
            model_label=pl_model,
        )
        summaries[f"Agentic GraphRAG Planned ({pl_model})"] = meta["aggregate"]

    # ── Summary table ─────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  OFFLINE METRICS SUMMARY (Phase 1 of 2)")
    print("=" * 80)
    col_w = 38
    p_headers = " | ".join(f"P@{k}  " for k in K_VALUES)
    print(f"  {'Pipeline':<{col_w}} | {p_headers} | AnswCont |  Faith | TSM    |  DF  | Lat(s) | Tokens | Err")
    print(f"  {'-'*col_w}-+--------+--------+----------+--------+--------+------+--------+--------+----")
    for name, agg in summaries.items():
        p_vals = " | ".join(
            f"{agg[f'avg_precision_at_{k}']:.4f}" if agg.get(f'avg_precision_at_{k}') is not None else "  N/A "
            for k in K_VALUES
        )
        ac = f"{agg['avg_answer_contains']:.4f}" if agg['avg_answer_contains'] is not None else "  N/A "
        faith = f"{agg['avg_title_faithfulness']:.4f}" if agg.get('avg_title_faithfulness') is not None else "  N/A "
        tsm = f"{agg['avg_tool_set_match']:.4f}" if agg.get('avg_tool_set_match') is not None else "  N/A "
        df = agg.get('total_destructive_filter_calls', 0)
        lat = f"{agg['avg_latency_seconds']:.1f}s"
        tok = f"{agg.get('avg_tokens_per_query', 0):.0f}"
        err = agg['error_count']
        print(f"  {name:<{col_w}} | {p_vals} | {ac}   | {faith} | {tsm} | {df:>4} | {lat:>6} | {tok:>6} | {err}")

    print("\n  Phase 2 (RAGAS Faithfulness + Answer Relevance):")
    print("    python evaluation/ragas_evaluation.py")
    print("  (atau --use-groq untuk pakai Groq sebagai judge LLM)")


if __name__ == "__main__":
    main()
