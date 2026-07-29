"""
evaluation/judge_manual_evaluation.py — Harness Manual LLM-as-a-Judge (Phase 2)
────────────────────────────────────────────────────────────────────────────────
TANPA API. Script ini HANYA mengurus bagian mekanis; penilaian skor
Faithfulness/Answer Relevance tetap dilakukan MANUAL oleh LLM judge (mis. Claude
Opus) di sesi terpisah, memakai rubrik di `evaluation/judge_prompt_phase2_manual.md`.

Dua mode:
  prepare : baca eval_results JSON (12 arm ablasi), ekstrak query/contexts/answer/
            reference + expected_titles (ground truth), ANONYMIZE + acak (blind),
            tulis 'judge_packet' self-contained + peta rahasia di folder TERPISAH.
            Path output (scores.csv) sudah ditanam ABSOLUT di JUDGE_INSTRUCTIONS →
            judge auto-simpan hasil balik ke repo tanpa copy manual.
  ingest  : baca scores.csv, un-blind via peta, agregasi per arm, tulis long-CSV +
            ringkasan markdown.

Alur:
  1) python evaluation/judge_manual_evaluation.py prepare
  2) PINDAHKAN 'judge_packet' ke folder kosong di luar repo → buka sesi Opus di sana
     → judge menilai + menulis scores.csv ke path repo yang sudah ditanam.
  3) python evaluation/judge_manual_evaluation.py ingest --run-dir hasil_judge/run_<ts>
"""

import argparse
import csv
import json
import os
import random
import re
import sys
from datetime import datetime
from statistics import mean

# ID simpul internal (mis. "book_106561") = artefak sistem, BUKAN klaim yang dilihat
# pengguna. Sebagian responder baseline membocorkannya; karena field ID tidak ikut
# diserialisasi ke `contexts`, judge keliru menandainya "dikarang" (false-flag,
# sekelas bug DDC). Kita normalisasi keluar dari teks yang dinilai agar Faithfulness
# hanya menilai klaim manusiawi (judul/penulis/kategori/DDC/ketersediaan/sinopsis).
# Beberapa varian format ID yang muncul: "(ID: book_x)", "[book_x]", "dengan ID
# book_x", "ID: book_x", dan bare "book_x". Dibersihkan bertahap lalu rapikan spasi.
_ID_BRACKET = re.compile(r"\s*[\(\[]\s*(?:ID:?\s*)?book_\d+\s*[\)\]]", re.IGNORECASE)
_ID_LABELED = re.compile(r"\s*\b(?:dengan\s+|ber-?)?ID:?\s*book_\d+", re.IGNORECASE)
_ID_BARE = re.compile(r"\s*book_\d+")
_WS = re.compile(r"[ \t]{2,}")


def _normalize_answer(text):
    """Buang token ID internal 'book_XXXX' dari teks yang dinilai judge (segala
    varian format), lalu rapikan spasi ganda yang tersisa."""
    if not text:
        return text
    text = _ID_BRACKET.sub("", text)
    text = _ID_LABELED.sub("", text)
    text = _ID_BARE.sub("", text)
    return _WS.sub(" ", text)

reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(reconfigure_stdout):
    reconfigure_stdout(encoding="utf-8")

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
HASIL_EVAL = os.path.join(EVAL_DIR, "hasil_eval")
HASIL_JUDGE = os.path.join(EVAL_DIR, "hasil_judge")
MAPS_DIR = os.path.join(HASIL_JUDGE, "blind_maps")  # peta rahasia — TERPISAH dari run_dir

# 12 arm: seluruh ladder ablasi × 2 model. Model diambil dari metadata.model tiap file.
# Default = berkas re-eval penuh final (lingkungan inferensi seragam, 28 Jul 2026),
# yang menjadi dasar penilaian Fase-2 definitif (run_20260727_073043).
DEFAULT_FILES = [
    ("Standard RAG", "eval_results_standard_llama31_reeval20260726_noaudit.json"),
    ("Standard RAG", "eval_results_standard_qwen25_reeval20260726_noaudit.json"),
    ("CoT-RAG",      "eval_results_cot_rag_llama31_reeval20260726_noaudit.json"),
    ("CoT-RAG",      "eval_results_cot_rag_qwen25_reeval20260726_noaudit.json"),
    ("Act-only",     "eval_results_act_only_llama31_reeval20260726_noaudit.json"),
    ("Act-only",     "eval_results_act_only_qwen25_reeval20260726_noaudit.json"),
    ("Pure ReAct",   "eval_results_pure_react_llama31_reeval20260726_noaudit.json"),
    ("Pure ReAct",   "eval_results_pure_react_qwen25_reeval20260726_noaudit.json"),
    ("SSG",          "eval_results_agentic_llama_reeval20260726_noaudit.json"),
    ("SSG",          "eval_results_agentic_qwen_reeval20260726_noaudit.json"),
    ("Planned",      "eval_results_planned_llama31_reeval20260726_noaudit.json"),
    ("Planned",      "eval_results_planned_qwen25_reeval20260726_noaudit.json"),
]

SCORE_COLUMNS = ["anon_id", "faithfulness", "answer_relevance", "justification"]


# ── prepare ─────────────────────────────────────────────────────────────────

def _load_ground_truth():
    """Peta query_id -> expected_titles dari ground_truth.json (anchor Answer Relevance).
    Aman untuk blind: expected_titles per-query (Q-level), sama untuk semua arm."""
    path = os.path.join(EVAL_DIR, "ground_truth.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return {e.get("id"): (e.get("expected_titles") or []) for e in data}


def _load_records(files):
    """Kumpulkan record judge-able dari tiap file. Skip error/empty-answer."""
    gt = _load_ground_truth()
    records = []
    for arm_label, fname in files:
        path = os.path.join(HASIL_EVAL, fname)
        if not os.path.exists(path):
            print(f"  ⚠️  Tidak ditemukan, dilewati: {fname}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        model = payload.get("metadata", {}).get("model", "?")
        n_ok = 0
        for r in payload.get("results", []):
            if r.get("error") or not r.get("answer"):
                continue
            records.append({
                "arm": arm_label,
                "model": model,
                "query_id": r.get("id"),
                "query_type": r.get("query_type"),
                "hop_count": r.get("hop_count"),
                "query": r.get("query"),
                "contexts": r.get("contexts") or [],
                "answer": r.get("answer"),
                "reference": r.get("reference_answer") or "",
                "expected_titles": gt.get(r.get("id"), []),
                "source_file": fname,
            })
            n_ok += 1
        print(f"  {arm_label:16} [{model:12}] {fname}  → {n_ok} record")
    return records


def _parse_files_arg(files_arg):
    """Parse token '--files' berformat 'Label::namafile.json' → [(label, fname), ...]."""
    out = []
    for tok in files_arg:
        if "::" not in tok:
            print(f"  ⚠️  Format --files salah (butuh 'Label::namafile.json'): {tok}")
            sys.exit(1)
        label, fname = tok.split("::", 1)
        out.append((label.strip(), fname.strip()))
    return out


def cmd_prepare(args):
    print("=" * 70)
    print("  PREPARE — ekstrak + blind (anonymize + shuffle)")
    print("=" * 70)
    files = _parse_files_arg(args.files) if args.files else DEFAULT_FILES
    records = _load_records(files)
    if not records:
        print("❌ Tidak ada record. Cek nama file di DEFAULT_FILES.")
        sys.exit(1)

    random.seed(args.seed)
    random.shuffle(records)  # blind: urutan acak lintas arm
    for i, rec in enumerate(records, start=1):
        rec["anon_id"] = f"A{i:04d}"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{ts}"
    run_dir = os.path.join(HASIL_JUDGE, run_id)
    packet_dir = os.path.join(run_dir, "judge_packet")   # self-contained → pindah ke luar repo
    os.makedirs(packet_dir, exist_ok=True)
    os.makedirs(MAPS_DIR, exist_ok=True)

    # 1) blind batch (DI DALAM packet) — TANPA arm/model/query_id
    with open(os.path.join(packet_dir, "blind_batch.jsonl"), "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps({
                "anon_id": rec["anon_id"],
                "query": rec["query"],
                "contexts": rec["contexts"],
                "answer": _normalize_answer(rec["answer"]),
                "reference": _normalize_answer(rec["reference"]),
                "expected_titles": rec["expected_titles"],
            }, ensure_ascii=False) + "\n")

    # 2) template skor (DI DALAM packet)
    with open(os.path.join(packet_dir, "scores_template.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SCORE_COLUMNS)
        for rec in records:
            w.writerow([rec["anon_id"], "", "", ""])

    # 3) output path yang di-EXPOSE ke judge (absolut, balik ke repo; run_dir kosong
    #    setelah packet dipindah → tak ada map/sumber di sekitarnya) + rubrik + instruksi
    scores_out_abs = os.path.abspath(os.path.join(run_dir, "scores.csv"))
    with open(os.path.join(packet_dir, "JUDGE_INSTRUCTIONS.md"), "w", encoding="utf-8") as f:
        f.write(_judge_instructions(len(records), scores_out_abs))

    # 4) peta rahasia — DI FOLDER TERPISAH (blind_maps/), BUKAN di run_dir → tak terlihat
    #    dari path output yang di-expose ke judge
    map_path = os.path.join(MAPS_DIR, f"{run_id}.csv")
    with open(map_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["anon_id", "arm", "model", "query_id", "query_type", "hop_count", "source_file"])
        for rec in records:
            w.writerow([rec["anon_id"], rec["arm"], rec["model"], rec["query_id"],
                        rec["query_type"], rec["hop_count"], rec["source_file"]])

    print("-" * 70)
    print(f"  Total record judge-able : {len(records)}")
    print(f"  PAKET JUDGE (blind)     : {os.path.relpath(packet_dir, EVAL_DIR)}")
    print("    isi: blind_batch.jsonl, JUDGE_INSTRUCTIONS.md (rubrik inline), scores_template.csv")
    print(f"  Peta rahasia (SIMPAN)   : {os.path.relpath(map_path, EVAL_DIR)}  ← di luar run_dir, judge tak tahu")
    print(f"  Judge AUTO-simpan ke    : {os.path.relpath(os.path.join(run_dir, 'scores.csv'), EVAL_DIR)}")
    print("    (path absolut sudah ditanam di JUDGE_INSTRUCTIONS → tak perlu copy manual)")
    print("\n  1) PINDAHKAN folder 'judge_packet' ke folder KOSONG di luar repo, buka sesi Opus DI SANA.")
    print("  2) Judge menilai + otomatis menulis scores.csv ke path repo di atas.")
    print(f"  3) python evaluation/judge_manual_evaluation.py ingest --run-dir {os.path.relpath(run_dir, os.getcwd())}")


def _judge_instructions(n, scores_out_abs):
    return f"""# INSTRUKSI SESI JUDGE (Manual LLM-as-a-Judge — Phase 2)

Kamu (LLM judge, mis. Claude Opus) menilai **{n} jawaban** sistem rekomendasi buku,
yang sudah **di-anonymize** (kamu TIDAK tahu jawaban dari sistem/model mana → blind).

> ⚠️ **JAGA BLIND-nya.** Baca HANYA file di folder ini. JANGAN membuka file/dokumen
> lain di komputer (blind_map, eval_results, docs repo, dsb.) — itu membocorkan
> arm/model dan merusak validitas blind. Fokus HANYA pada penilaian.

## Data
Baca `blind_batch.jsonl` — satu record per baris: `anon_id`, `query`, `contexts`,
`answer`, `reference`, `expected_titles`. Untuk TIAP record beri skor 2 metrik
(0.0–1.0) + justifikasi 1 kalimat, sesuai RUBRIK di bawah.

## RUBRIK PENILAIAN

### METRIK 1 — FAITHFULNESS (grounding terhadap `contexts`)
Proporsi klaim faktual dalam `answer` yang DIDUKUNG LANGSUNG oleh `contexts`. Nilai
**HANYA terhadap `contexts`** — JANGAN pakai pengetahuan umum, JANGAN pakai
`reference`/`expected_titles` untuk metrik ini.
- Menurunkan skor: judul/penulis/cabang/nuansa/ketersediaan yang disebut di `answer`
  tapi TIDAK ADA di `contexts` atau BERTENTANGAN; sinopsis fiktif.
- **JANGAN menilai ID/kode internal.** ID simpul database (mis. `book_106561`) adalah
  artefak sistem, BUKAN klaim faktual untuk pengguna. Bila muncul di `answer`, ABAIKAN
  — jangan hitung sebagai "dikarang". Nilai HANYA klaim manusiawi (judul, penulis,
  kategori, vibe, DDC, ketersediaan, sinopsis).
- **Kasus khusus:** `contexts` KOSONG + `answer` jujur "tidak ditemukan" →
  Faithfulness **TINGGI (≈1.0)** (tak ada yang dikarang).
- Jangkar: `1.0` = semua klaim didukung · `~0.5` = campuran didukung/tidak ·
  `0.0` = bertentangan / klaim inti tak didukung.

### METRIK 2 — ANSWER RELEVANCE (kualitas & ketepatan rekomendasi yang disajikan)
Seberapa baik rekomendasi yang BENAR-BENAR disajikan di `answer` menjawab maksud
`query`. Ini tugas **rekomendasi**: sampel buku yang relevan dan tepat sudah memenuhi
kebutuhan — **JANGAN menuntut cakupan menyeluruh** terhadap seluruh `expected_titles`.
Jawaban ringkas berisi beberapa judul relevan yang tepat = TINGGI; jumlah judul (mis.
"hanya 6 dari 96") **bukan** alasan menurunkan skor. `reference` & `expected_titles`
dipakai sebagai **acuan relevansi** (apakah judul yang disodorkan memang termasuk/
konsisten dgn buku relevan), BUKAN kuota cakupan. Pakai `expected_titles` HANYA di sini.
- **Kasus khusus:** `answer` "tidak ditemukan" TAPI `reference`/`expected_titles`
  menunjukkan buku relevan ADA → Answer Relevance **RENDAH (≈0.1)** (kebutuhan tak
  terpenuhi, meski Faithfulness bisa tinggi).
- Menurunkan skor: judul yang disodorkan menyimpang dari maksud query (mis. mencampur
  buku di luar topik tanpa keterangan), atau jawaban kabur/tidak actionable.
- Jangkar: `1.0` = judul yang disajikan relevan & menjawab maksud (walau sedikit) ·
  `~0.5` = sebagian relevan / ada yang melenceng · `0.1` = gagal memenuhi kebutuhan.

### Aturan
- Skor kedua metrik TERPISAH (bisa Faithfulness tinggi + Answer Relevance rendah).
- Justifikasi sebut bukti spesifik (judul/atribut), bukan umum. Konsisten dgn jangkar.

## Output — tulis LANGSUNG ke file (path ABSOLUT) ini
Kolom `anon_id,faithfulness,answer_relevance,justification`:

```
{scores_out_abs}
```

Buat foldernya bila perlu. Kerjakan bertahap (50–100 record/giliran); jangan lewati
satu pun `anon_id`. Jangan menulis/membaca file lain selain output ini.

## Setelah selesai
Beri tahu user bahwa scores.csv sudah tersimpan. User jalankan:
`python evaluation/judge_manual_evaluation.py ingest --run-dir <run_dir>`
"""


# ── ingest ──────────────────────────────────────────────────────────────────

def _to_float(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def _read_scores(path):
    """Baca scores.csv → dict anon_id -> (faith, ans_rel, justification)."""
    scores = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            aid = (row.get("anon_id") or "").strip()
            if not aid:
                continue
            scores[aid] = (
                _to_float(row.get("faithfulness")),
                _to_float(row.get("answer_relevance")),
                (row.get("justification") or "").strip(),
            )
    return scores


def _find_map(run_dir):
    """Cari peta rahasia: blind_maps/<run_id>.csv, fallback run_dir/blind_map.csv."""
    run_id = os.path.basename(os.path.normpath(run_dir))
    for c in (os.path.join(MAPS_DIR, f"{run_id}.csv"), os.path.join(run_dir, "blind_map.csv")):
        if os.path.exists(c):
            return c
    return None


def cmd_ingest(args):
    run_dir = args.run_dir
    map_path = _find_map(run_dir)
    scores_path = args.scores or os.path.join(run_dir, "scores.csv")
    if not map_path:
        print(f"❌ Peta rahasia tidak ditemukan untuk {run_dir} (cek {os.path.relpath(MAPS_DIR, EVAL_DIR)}).")
        sys.exit(1)
    if not os.path.exists(scores_path):
        print(f"❌ File skor tidak ada: {scores_path}\n   (judge harus menulis scores.csv dulu)")
        sys.exit(1)

    scores = _read_scores(scores_path)
    with open(map_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    long_rows, missing = [], 0
    for m in rows:
        s = scores.get(m["anon_id"])
        if s is None:
            missing += 1
            faith = ans = just = None
        else:
            faith, ans, just = s
        long_rows.append({
            "arm": m["arm"], "model": m["model"], "query_id": m["query_id"],
            "query_type": m["query_type"], "hop_count": m["hop_count"],
            "faithfulness": faith, "answer_relevance": ans, "justification": just,
        })

    long_path = os.path.join(run_dir, "phase2_manual_long.csv")
    with open(long_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["arm", "model", "query_id", "query_type",
                                          "hop_count", "faithfulness", "answer_relevance",
                                          "justification"])
        w.writeheader()
        w.writerows(long_rows)

    groups = {}
    for r in long_rows:
        groups.setdefault((r["arm"], r["model"]), []).append(r)

    summary = []
    for (arm, model), rs in sorted(groups.items()):
        fvals = [r["faithfulness"] for r in rs if r["faithfulness"] is not None]
        avals = [r["answer_relevance"] for r in rs if r["answer_relevance"] is not None]
        summary.append({
            "arm": arm, "model": model, "n": len(rs), "n_scored": len(fvals),
            "faith": round(mean(fvals), 4) if fvals else None,
            "ans_rel": round(mean(avals), 4) if avals else None,
        })

    _write_summary_md(run_dir, summary, missing, scores_path)

    print("=" * 78)
    print("  RINGKASAN PHASE 2 (Manual LLM-as-a-Judge)")
    print("=" * 78)
    print(f"  {'Arm':16} {'Model':12} {'n':>4} {'scored':>7} {'Faith':>8} {'AnsRel':>8}")
    print("  " + "-" * 60)
    for s in summary:
        fs = f"{s['faith']:.4f}" if s["faith"] is not None else "N/A"
        as_ = f"{s['ans_rel']:.4f}" if s["ans_rel"] is not None else "N/A"
        print(f"  {s['arm']:16} {s['model']:12} {s['n']:>4} {s['n_scored']:>7} {fs:>8} {as_:>8}")
    if missing:
        print(f"\n  ⚠️  {missing} record belum ada skornya di scores.csv (dihitung kosong).")
    print(f"\n  Long CSV : {os.path.relpath(long_path, EVAL_DIR)}")
    print(f"  Ringkasan: {os.path.relpath(os.path.join(run_dir, 'phase2_manual_summary.md'), EVAL_DIR)}")


def _write_summary_md(run_dir, summary, missing, scores_path):
    lines = [
        "# Phase 2 — Manual LLM-as-a-Judge (Ringkasan)",
        "",
        f"> Sumber skor: `{os.path.basename(scores_path)}` · di-generate {datetime.now():%Y-%m-%d %H:%M}",
        "> **Label metodologi**: Manual/Interactive LLM-as-a-Judge Protocol "
        "(judge: Claude [MODEL], [TANGGAL]) — bukan RAGAS otomatis. Blind (anonymize + shuffle + isolasi).",
        "> Limitasi lengkap: `docs/catatan_riset.md §9`.",
        "",
        "| Arm | Model | n | scored | Avg Faithfulness | Avg Answer Relevance |",
        "|---|---|---|---|---|---|",
    ]
    for s in summary:
        fs = f"{s['faith']:.4f}" if s["faith"] is not None else "N/A"
        as_ = f"{s['ans_rel']:.4f}" if s["ans_rel"] is not None else "N/A"
        lines.append(f"| {s['arm']} | {s['model']} | {s['n']} | {s['n_scored']} | {fs} | {as_} |")
    if missing:
        lines += ["", f"> ⚠️ {missing} record belum dinilai (kosong di scores.csv)."]
    lines += ["", "> Salin tabel ini ke **Bab 4 §4.6.2**. Detail per-query: `phase2_manual_long.csv`."]
    with open(os.path.join(run_dir, "phase2_manual_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Harness Manual LLM-as-a-Judge (Phase 2) — tanpa API")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare", help="Ekstrak + blind → judge_packet self-contained")
    pp.add_argument("--seed", type=int, default=42, help="Seed shuffle (reproducible blind).")
    pp.add_argument("--files", nargs="+", default=None,
                    help="Override daftar file: token 'Label::eval_results_x.json' "
                         "(default: 12 arm kanonik). Mis. --files 'Planned::eval_results_planned_qwen25_20260719_merged.json'.")
    pp.set_defaults(func=cmd_prepare)

    pi = sub.add_parser("ingest", help="Baca scores.csv → un-blind + agregasi")
    pi.add_argument("--run-dir", required=True, help="Folder run_<ts> hasil prepare.")
    pi.add_argument("--scores", default=None, help="Path scores.csv (default: <run-dir>/scores.csv).")
    pi.set_defaults(func=cmd_ingest)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
