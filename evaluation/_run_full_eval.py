# -*- coding: utf-8 -*-
"""Driver re-eval penuh 12 arm × 100 kueri — BATCHED (4×25) agar tahan tunnel putus.
Retry 3× per batch, merge otomatis per arm, RESUMABLE (skip arm yang sudah selesai).
Config final: --no-self-correct (audit-off). Jalankan di background; ulangi bila
sebagian gagal (job yang sudah punya file final akan dilewati)."""
import subprocess, os, sys, json, re, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
RUNNER = os.path.join("evaluation", "run_comparative_evaluation.py")
HASIL = os.path.join(ROOT, "evaluation", "hasil_eval")
LLAMA, QWEN = "llama3.1:8b", "qwen2.5:7b"
BATCH = 25
STARTS = [0, 25, 50, 75]
TS = "reeval20260726"

# (slug_final, pipeline_flag, extra_flags, model_label)
JOBS = [
    ("standard_llama31",  "standard",   ["--llama-model", LLAMA], LLAMA),
    ("standard_qwen25",   "standard",   ["--llama-model", QWEN],  QWEN),
    ("cot_rag_llama31",   "cot",        ["--cot-model", LLAMA],   LLAMA),
    ("cot_rag_qwen25",    "cot",        ["--cot-model", QWEN],    QWEN),
    ("act_only_llama31",  "act_only",   ["--act-only-model", LLAMA], LLAMA),
    ("act_only_qwen25",   "act_only",   ["--act-only-model", QWEN],  QWEN),
    ("pure_react_llama31","pure_react", ["--pure-react-model", LLAMA], LLAMA),
    ("pure_react_qwen25", "pure_react", ["--pure-react-model", QWEN],  QWEN),
    ("agentic_llama",     "llama",      [], LLAMA),   # SSG (Search-Space-Gated) — Llama
    ("agentic_qwen",      "qwen",       [], QWEN),    # SSG — Qwen (pakai --qwen-model default)
    ("planned_llama31",   "planned",    ["--planned-model", LLAMA], LLAMA),
    ("planned_qwen25",    "planned",    ["--planned-model", QWEN],  QWEN),
]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def run_batch(pipeline, flags, start):
    cmd = [PY, RUNNER, "--pipelines", pipeline, *flags, "--no-self-correct",
           "--start", str(start), "--limit", str(BATCH)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, encoding="utf-8",
                           errors="replace", env=env, timeout=6000)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    out = None
    for line in (r.stdout or "").splitlines():
        mm = re.search(r"Output:\s*(eval_results_\S+\.json)", line)
        if mm:
            out = mm.group(1)
    return out, r.returncode


def main():
    total_ok = 0
    for slug, pipeline, flags, model in JOBS:
        final = os.path.join(HASIL, f"eval_results_{slug}_{TS}_noaudit.json")
        if os.path.exists(final):
            log(f"SKIP {slug} (file final sudah ada)"); total_ok += 1; continue
        log(f"===== JOB {slug}  (pipeline={pipeline}, model={model}) =====")
        merged, meta, ok_all = [], None, True
        for s in STARTS:
            done = False
            for attempt in range(1, 4):
                out, rc = run_batch(pipeline, flags, s)
                if out is None:
                    log(f"  start={s} att{attempt}: tak ada output (rc={rc})"); continue
                try:
                    d = json.load(open(os.path.join(HASIL, out), encoding="utf-8"))
                except Exception as ex:
                    log(f"  start={s} att{attempt}: gagal baca {out} ({ex})"); continue
                res = d.get("results", [])
                n_err = sum(1 for x in res if x.get("error"))
                if len(res) >= BATCH and n_err == 0:
                    meta = meta or d.get("metadata", {})
                    merged.extend(res)
                    log(f"  start={s}: OK ({len(res)} res, 0 err)")
                    done = True; break
                log(f"  start={s} att{attempt}: belum lengkap ({len(res)} res, {n_err} err) — retry")
            if not done:
                log(f"  start={s}: GAGAL 3× — job {slug} belum lengkap, lanjut job lain")
                ok_all = False; break
        if ok_all and len(merged) >= 100:
            meta = meta or {}
            meta.update({"model": model, "total_queries": len(merged),
                         "note": f"full re-eval {TS} (batched 4x25; GT+responder+build_contexts+tool fixes)"})
            json.dump({"metadata": meta, "results": merged},
                      open(final, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            log(f"===== {slug} SELESAI → {os.path.basename(final)} ({len(merged)} kueri) =====")
            total_ok += 1
        else:
            log(f"===== {slug} BELUM LENGKAP ({len(merged)} kueri) — ulangi driver nanti =====")
    log(f"DRIVER SELESAI — {total_ok}/{len(JOBS)} arm lengkap")


if __name__ == "__main__":
    main()
