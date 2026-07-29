#!/usr/bin/env bash
# evaluation/run_ablation_queue.sh
# ─────────────────────────────────────────────────────────────────────────
# Antrian (queue) ablasi berurutan — menjalankan 3 arm ablasi opt-in
# (cot, pure_react, act_only) untuk SETIAP model, satu model dalam satu waktu.
#
# Aman ditinggal jalan tanpa diawasi:
#   • output tiap model ditulis ke log-nya sendiri di hasil_eval/queue_logs/
#   • satu arm yang gagal TIDAK menghentikan sisa antrian (continue-on-fail)
#   • ada preflight cek Ollama supaya kalau tunnel putus ketahuan di awal
#
# Pakai:
#   bash evaluation/run_ablation_queue.sh
#   bash evaluation/run_ablation_queue.sh llama3.1:8b qwen2.5:7b        # daftar model custom
#
# Setiap run menulis file hasil ber-timestamp (tidak menimpa run lama):
#   evaluation/hasil_eval/eval_results_cot_rag_<slug>_<timestamp>.json
#   evaluation/hasil_eval/eval_results_pure_react_<slug>_<timestamp>.json
#   evaluation/hasil_eval/eval_results_act_only_<slug>_<timestamp>.json

set -u  # sengaja TIDAK set -e: kita mau lanjut walau satu run gagal

# ── project root (script ini ada di evaluation/) ─────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "FATAL: gagal cd ke project root"; exit 1; }

# Pakai interpreter .venv secara eksplisit — proses background belum tentu
# punya .venv di PATH.
PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"

MODELS=("$@")
[ ${#MODELS[@]} -eq 0 ] && MODELS=("llama3.1:8b" "qwen2.5:7b")

PIPELINES=(cot pure_react act_only)

LOGDIR="$ROOT/evaluation/hasil_eval/queue_logs"
mkdir -p "$LOGDIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
MASTER="$LOGDIR/queue_${STAMP}.log"

log() { echo "$@" | tee -a "$MASTER"; }

log "===================================================================="
log "  ABLATION QUEUE — mulai $(date '+%Y-%m-%d %H:%M:%S')"
log "  models    : ${MODELS[*]}"
log "  pipelines : ${PIPELINES[*]}"
log "  python    : $PY"
log "  master log: $MASTER"
log "===================================================================="

# ── preflight: Ollama kejangkau? (non-fatal, cuma warning) ───────────────
BASE_URL="$(grep -E '^OLLAMA_BASE_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r')"
if [ -n "${BASE_URL:-}" ]; then
    code="$(curl -s -m 10 "$BASE_URL/api/tags" -o /dev/null -w '%{http_code}' || echo 000)"
    if [ "$code" = "200" ]; then
        log "  OK  Ollama kejangkau di $BASE_URL (HTTP 200)"
    else
        log "  WARN Ollama di $BASE_URL TIDAK kejangkau (HTTP $code)."
        log "       Queue tetap jalan; query akan error sampai server balik."
    fi
fi

overall_start=$(date +%s)
declare -a SUMMARY=()

for MODEL in "${MODELS[@]}"; do
    slug="$(echo "$MODEL" | tr -d ':.' | tr '/' '_')"
    mlog="$LOGDIR/ablation_${slug}_${STAMP}.log"
    log ""
    log "────────────────────────────────────────────────────────────────────"
    log "  >> START  $MODEL   $(date '+%H:%M:%S')"
    log "     log -> $mlog"
    log "────────────────────────────────────────────────────────────────────"
    mstart=$(date +%s)

    "$PY" evaluation/run_comparative_evaluation.py \
        --pipelines "${PIPELINES[@]}" \
        --cot-model "$MODEL" \
        --pure-react-model "$MODEL" \
        --act-only-model "$MODEL" \
        > "$mlog" 2>&1
    status=$?

    mend=$(date +%s); dur=$(( mend - mstart ))
    if [ $status -eq 0 ]; then
        log "  OK   DONE  $MODEL  dalam $((dur/60))m$((dur%60))s  (exit 0)"
        SUMMARY+=("OK    $MODEL  ($((dur/60))m$((dur%60))s)")
    else
        log "  XX   FAIL  $MODEL  (exit $status) setelah $((dur/60))m$((dur%60))s — cek $mlog"
        SUMMARY+=("FAIL  $MODEL  (exit $status)")
    fi
done

overall_end=$(date +%s); total=$(( overall_end - overall_start ))
log ""
log "===================================================================="
log "  ABLATION QUEUE — selesai $(date '+%Y-%m-%d %H:%M:%S')"
log "  total wall time: $((total/60))m$((total%60))s"
for s in "${SUMMARY[@]}"; do log "    $s"; done
log ""
log "  file hasil -> evaluation/hasil_eval/eval_results_{cot_rag,pure_react,act_only}_<slug>_*.json"
log "===================================================================="
