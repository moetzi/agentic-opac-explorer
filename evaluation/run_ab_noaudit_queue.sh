#!/usr/bin/env bash
# evaluation/run_ab_noaudit_queue.sh
# ─────────────────────────────────────────────────────────────────────────
# A/B "audit OFF": jalankan ulang arm yang PAKAI responder self-correct dengan
# self-correct DIMATIKAN (--no-self-correct), buat dibandingkan ke run "audit
# ON" tanggal 6-7 Juli. Mengukur trade-off audit self-correct (catatan_riset.md
# § 4.1: fire 47%, fix cuma 8%, arm tanpa audit malah lebih faithful).
#
#   1. VG-v2 (llama)   -> eval_results_agentic_llama_<ts>_noaudit.json
#   2. VG-v2 (qwen)    -> eval_results_agentic_qwen_<ts>_noaudit.json
#   3. Planned (llama) -> eval_results_planned_llama31_<ts>_noaudit.json
#   4. Planned (qwen)  -> eval_results_planned_qwen25_<ts>_noaudit.json
#
# KENAPA cuma 4 arm ini (bukan "semua 6 skenario"):
#   • Standard RAG & CoT-RAG  -> tidak memakai responder_node sama sekali
#     (generate sendiri di standard_rag.py) → self-correct tak berlaku.
#   • Act-only & Pure ReAct   -> SUDAH self_correct=False by design → run
#     "audit ON"-nya tak ada, jadi mereka sendiri adalah titik "audit OFF"
#     buat arm loop. Re-run cuma mereproduksi angka lama (noise LLM).
#   Jadi A/B audit on/off yang bermakna HANYA VG-v2 & Planned.
#   (Kalau tetap mau grid OFF lengkap: tambah `--pipelines standard cot ...`
#    dengan --no-self-correct sendiri — flag-nya global.)
#
# Per-pipeline + retry 1x. Jalankan hanya saat GPU server tidak di-share.
# Pakai:  bash evaluation/run_ab_noaudit_queue.sh

set -u
export PYTHONUNBUFFERED=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "FATAL: gagal cd ke project root"; exit 1; }

PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"

LOGDIR="$ROOT/evaluation/hasil_eval/queue_logs"
mkdir -p "$LOGDIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
MASTER="$LOGDIR/ab_noaudit_${STAMP}.log"
log() { echo "$@" | tee -a "$MASTER"; }

# ── preflight: GPU server up? ────────────────────────────────────────────
BASE_URL="$(grep -E '^OLLAMA_BASE_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r')"
if [ -n "${BASE_URL:-}" ]; then
    code="$(curl -s -m 10 "$BASE_URL/api/tags" -o /dev/null -w '%{http_code}' || echo 000)"
    if [ "$code" = "200" ]; then
        log "  OK  Ollama up di $BASE_URL"
    else
        log "  XX  Ollama TIDAK kejangkau ($BASE_URL, HTTP $code). Nyalakan server dulu."
        exit 1
    fi
fi

log "===================================================================="
log "  A/B AUDIT-OFF (VG-v2 + Planned, self_correct=False) — $(date '+%Y-%m-%d %H:%M:%S')"
log "  python : $PY  |  master: $MASTER"
log "===================================================================="

declare -a SUMMARY=()
run_pipeline_retry() {
    local label="$1"; shift
    local attempt=1 status=1 plog t0 dur
    while [ $attempt -le 2 ]; do
        plog="$LOGDIR/run_${label}_${STAMP}_a${attempt}.log"
        log "  [$(date '+%H:%M:%S')] >> $label (attempt $attempt) -> $(basename "$plog")"
        t0=$(date +%s)
        "$PY" evaluation/run_comparative_evaluation.py "$@" --no-self-correct > "$plog" 2>&1
        status=$?; dur=$(( $(date +%s) - t0 ))
        if [ $status -eq 0 ]; then
            log "  [$(date '+%H:%M:%S')]    OK $label ($((dur/60))m$((dur%60))s)"
            SUMMARY+=("OK    $label ($((dur/60))m$((dur%60))s)"); return 0
        fi
        log "  [$(date '+%H:%M:%S')]    CRASH $label (exit $status, $((dur/60))m$((dur%60))s)"
        attempt=$((attempt+1)); [ $attempt -le 2 ] && { log "      retry 30s..."; sleep 30; }
    done
    SUMMARY+=("FAIL  $label (exit $status)"); return $status
}

overall=$(date +%s)
run_pipeline_retry "vgated_v2_llama_noaudit" --pipelines llama   --llama-model llama3.1:8b
run_pipeline_retry "vgated_v2_qwen_noaudit"  --pipelines qwen    --qwen-model  qwen2.5:7b
run_pipeline_retry "planned_llama_noaudit"   --pipelines planned --planned-model llama3.1:8b
run_pipeline_retry "planned_qwen_noaudit"    --pipelines planned --planned-model qwen2.5:7b

log ""
log "===================================================================="
log "  A/B AUDIT-OFF — selesai $(date '+%Y-%m-%d %H:%M:%S')  (total $(( ($(date +%s)-overall)/60 ))m)"
for s in "${SUMMARY[@]}"; do log "    $s"; done
log "  File OFF bertag '_noaudit'; bandingkan ke run ON (tanpa tag) per (arm,model)."
log "===================================================================="
