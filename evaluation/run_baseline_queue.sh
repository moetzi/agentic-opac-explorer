#!/usr/bin/env bash
# evaluation/run_baseline_queue.sh
# ─────────────────────────────────────────────────────────────────────────
# Menjalankan pipeline evaluasi NON-ablasi yang tersisa, satu pipeline per
# proses supaya crash transien hanya me-retry pipeline itu (bukan mengulang
# semua). Empat run, berurutan:
#
#   1. Standard RAG        (llama3.1:8b)  -> eval_results_standard_*.json        (metadata.model=llama3.1:8b)
#   2. Vector-Gated ReAct  (llama3.1:8b)  -> eval_results_agentic_llama_*.json
#   3. Vector-Gated ReAct  (qwen2.5:7b)   -> eval_results_agentic_qwen_*.json
#   4. Standard RAG        (qwen2.5:7b)   -> eval_results_standard_*.json        (metadata.model=qwen2.5:7b)
#
# Kenapa Standard RAG dua kali (llama & qwen): Standard RAG = Retrieve
# (SentenceTransformer, model-independent -> P@K identik) + GENERATE (llm.invoke
# -> tergantung model). Jadi AC/faithfulness/latency/token beda antar model;
# perbandingan CoT-RAG(m) vs Standard(m) butuh Standard di model m yang sama.
#
# Kedua file standard TANPA slug model di nama file — dibedakan lewat
# metadata.model di dalam file (persis cara analyze_by_query_type.py memilah:
# key = "Standard RAG [<model>]").
#
# Retry: run 08:04 mati dengan exit 127 TRANSIEN persis setelah ablasi 6 jam
# kelar (qwen masih di VRAM + transisi state server). Tiap pipeline di-retry
# 1x kalau exit != 0, dengan jeda supaya state server sempat settle.
#
# Pakai:  bash evaluation/run_baseline_queue.sh

set -u
export PYTHONUNBUFFERED=1  # supaya traceback ke-flush kalau crash (bukan hilang di buffer)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "FATAL: gagal cd ke project root"; exit 1; }

PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"

LOGDIR="$ROOT/evaluation/hasil_eval/queue_logs"
mkdir -p "$LOGDIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
MASTER="$LOGDIR/baseline_${STAMP}.log"
log() { echo "$@" | tee -a "$MASTER"; }

# ── tunggu queue ablasi yang masih in-flight (kalau ada) ─────────────────
prev="$(ls -t "$LOGDIR"/queue_*.log 2>/dev/null | head -1)"
if [ -n "${prev:-}" ] && ! grep -q "selesai" "$prev"; then
    log "  [$(date '+%H:%M:%S')] nunggu queue ablasi selesai dulu: $(basename "$prev")"
    while [ -n "$prev" ] && ! grep -q "selesai" "$prev"; do
        sleep 30
    done
    log "  [$(date '+%H:%M:%S')] queue ablasi SELESAI — GPU bebas, mulai baseline"
fi

log "===================================================================="
log "  BASELINE + VECTOR-GATED (per-pipeline, retry 1x) — $(date '+%Y-%m-%d %H:%M:%S')"
log "  python : $PY"
log "  master : $MASTER"
log "===================================================================="

declare -a SUMMARY=()

# run_pipeline_retry <label> <args...>  — jalankan runner untuk satu pipeline,
# retry sekali kalau hard-crash (exit != 0).
run_pipeline_retry() {
    local label="$1"; shift
    local attempt=1 status=1 plog
    while [ $attempt -le 2 ]; do
        plog="$LOGDIR/run_${label}_${STAMP}_a${attempt}.log"
        log "  [$(date '+%H:%M:%S')] >> $label  (attempt $attempt)  -> $(basename "$plog")"
        local t0=$(date +%s)
        "$PY" evaluation/run_comparative_evaluation.py "$@" > "$plog" 2>&1
        status=$?
        local dur=$(( $(date +%s) - t0 ))
        if [ $status -eq 0 ]; then
            log "  [$(date '+%H:%M:%S')]    OK  $label  ($((dur/60))m$((dur%60))s)"
            SUMMARY+=("OK    $label  ($((dur/60))m$((dur%60))s)")
            return 0
        fi
        log "  [$(date '+%H:%M:%S')]    CRASH $label (exit $status) setelah $((dur/60))m$((dur%60))s — cek $(basename "$plog")"
        attempt=$((attempt+1))
        if [ $attempt -le 2 ]; then log "      retry dalam 30s..."; sleep 30; fi
    done
    log "  [$(date '+%H:%M:%S')]    GAGAL $label setelah 2 attempt (exit $status)"
    SUMMARY+=("FAIL  $label  (exit $status)")
    return $status
}

overall_start=$(date +%s)

run_pipeline_retry "standard_llama" --pipelines standard --llama-model llama3.1:8b
run_pipeline_retry "vgated_llama"   --pipelines llama    --llama-model llama3.1:8b
run_pipeline_retry "vgated_qwen"    --pipelines qwen     --qwen-model  qwen2.5:7b
run_pipeline_retry "standard_qwen"  --pipelines standard --llama-model qwen2.5:7b

total=$(( $(date +%s) - overall_start ))
log ""
log "===================================================================="
log "  BASELINE + VECTOR-GATED — selesai $(date '+%Y-%m-%d %H:%M:%S')"
log "  total wall time: $((total/60))m$((total%60))s"
for s in "${SUMMARY[@]}"; do log "    $s"; done
log ""
log "  file hasil -> eval_results_standard_*.json (x2: llama & qwen, beda metadata.model)"
log "                eval_results_agentic_llama_*.json, eval_results_agentic_qwen_*.json"
log "===================================================================="
