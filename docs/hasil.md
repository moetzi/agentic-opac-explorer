# Hasil Evaluasi

Laporan hasil aktual dari menjalankan framework evaluasi yang dijelaskan di
[`evaluasi.md`](evaluasi.md) — definisi metrik, ground truth, dan cara
menjalankan evaluasi ada di sana. Dokumen ini isinya angka/temuan dari run
yang sudah dilakukan.

---

## ⭐ Ringkasan FINAL (28 Juli 2026): Re-eval Seragam + Re-judge Blind Penuh

> **Ini angka otoritatif untuk skripsi** (Bab IV). Menggantikan seluruh ringkasan
> bertanggal lebih awal di bawah, yang kini bersifat **historis/superseded** —
> dibiarkan untuk merekam perjalanan riset (VG-v1→v2, A/B audit), **bukan** untuk
> dikutip sebagai hasil final.

Dua pemutakhiran menyeluruh dijalankan sebagai respons revisi sidang:

1. **Re-eval Fase 1 penuh (12 arm × 100 kueri)** pada **lingkungan inferensi seragam
   & tak-terbagi** (GPU dedicated, `n=100 / 0 error` tiap arm) — berkas
   `eval_results_<arm>_reeval20260726_noaudit.json`. Karena semua arm diukur di
   perangkat/lingkungan yang **sama**, latensi kini *apple-to-apple*.
2. **Re-judge Fase 2 blind penuh (1.200 jawaban)** oleh Claude Opus 4.8 —
   `hasil_judge/run_20260727_073043` — dengan rubrik yang disempurnakan (Answer
   Relevance = *kualitas sampel* rekomendasi, bukan cakupan; normalisasi ID simpul
   internal agar tak salah-vonis halusinasi).

### Matriks FINAL (12 arm × 2 model)

| Strategi | Model | P@3 | P@5 | AnswCont | Faith | AnsRel | TSM | Latensi | Token |
|---|---|---|---|---|---|---|---|---|---|
| Standard RAG | Llama | 0,177 | 0,160 | 0,817 | 0,765 | 0,476 | – | 6.4s | 3.344 |
| Standard RAG | Qwen | 0,177 | 0,160 | 0,902 | 0,723 | 0,460 | – | 8.3s | 3.477 |
| CoT-RAG | Llama | 0,177 | 0,160 | 0,650 | 0,645 | 0,374 | – | 18.3s | 3.874 |
| CoT-RAG | Qwen | 0,177 | 0,160 | 0,922 | 0,671 | 0,366 | – | 16.5s | 3.893 |
| Act-only | Llama | 0,503 | 0,406 | 0,945 | 0,858 | 0,683 | 0,807 | 21.3s | 10.725 |
| Act-only | Qwen | 0,587 | 0,428 | 0,890 | 0,879 | 0,750 | 0,800 | 19.4s | 8.541 |
| Pure ReAct | Llama | 0,550 | 0,442 | 0,885 | 0,870 | 0,688 | 0,670 | 23.6s | 9.414 |
| Pure ReAct | Qwen | 0,603 | 0,440 | 0,870 | 0,883 | 0,768 | 0,750 | 24.2s | 8.682 |
| SSG (Search-Space-Gated) | Llama | 0,560 | 0,396 | 0,945 | 0,870 | 0,759 | 0,703 | 22.5s | 5.992 |
| SSG (Search-Space-Gated) | Qwen | 0,510 | 0,380 | 0,902 | 0,856 | 0,737 | 0,677 | 22.6s | 6.049 |
| **Planned** | Llama | **0,823** | 0,788 | 0,907 | 0,872 | 0,809 | 0,825 | 21.4s | 6.320 |
| **Planned** 🏆 | Qwen | **0,903** | **0,854** | 0,940 | 0,860 | **0,885** | 0,858 | 22.6s | 6.541 |

### Temuan FINAL

1. **Planned + Qwen 2.5 = konfigurasi terbaik** — P@3 **0,903** dan Answer Relevance
   **0,885** (per-hop 0,86 → 0,90 → 0,92), tertinggi lintas seluruh arm.
2. **Latensi kini merata (~19–26 s) di semua arm agentik** — klaim lama "Planned ~2×
   lebih cepat (13 s)" adalah **artefak lingkungan tak-seragam** dan **gugur**.
   Pembeda efisiensi bergeser ke **token**: Planned (~6,3–6,5 rb) & SSG (~6 rb) jauh
   lebih hemat daripada loop Act-only/Pure ReAct (~8,5–10,7 rb).
3. **Faithfulness seragam tinggi di arm ber-acting (0,86–0,88)** — Planned **bukan**
   yang tertinggi (Pure ReAct Qwen 0,883); keunggulan Planned ada di **relevansi**,
   bukan keterpijakan.
4. **CoT-RAG Faith (0,65/0,67) lebih rendah dari Standard RAG (0,72/0,77)** —
   penalaran CoT menambah klaim tak-terpijak tanpa memperbaiki temu balik.
5. **Jurang relevansi (~0,3–0,4) ≫ jurang keterpijakan (~0,1–0,2)** — acting AnsRel
   0,68–0,89 vs non-acting 0,37–0,48; pembeda efektivitas yang dominan adalah
   **relevansi jawaban**.

Rincian lengkap (per tipe kueri, per hop, analisis ablasi) ada di
`docs/skripsi/bab4_hasil_v2.md`; data mentah per-kueri di
`docs/skripsi/lampiran_hasil_fase1.csv` dan
`hasil_judge/run_20260727_073043/phase2_manual_long.csv`.

---

## Ringkasan Terbaru (7 Juli 2026): Perbaikan Vector-Gated (v2) + Arm Planned — ⚠️ SUPERSEDED

> ⚠️ **SUPERSEDED oleh Ringkasan FINAL di atas.** Angka di bagian ini berasal dari
> run **lingkungan tak-seragam** (mis. Planned Qwen P@3 0,713, latensi 13,1 s) dan
> **tidak** dipakai di skripsi. Dipertahankan sebagai catatan perjalanan riset.

Breakdown per-hop pada ringkasan 5-skenario di bawah mengungkap **Vector-Gated
ambruk di multi-hop** (P@3 3-hop ~0.10) — padahal justru sistem utama. Root
cause: gating v1 mempersempit **action space** (route "vector" hanya boleh
`filter_*`; tool kombinasi multi-hop `books_by_*_and_*` & collaborative diblok),
bukan search space — jadi query multi-atribut tak pernah bisa memanggil tool
yang mereka butuhkan. Dua perubahan arsitektur menyusul (detail:
[catatan_riset.md § 4.1](catatan_riset.md), [workflow.py](../agent/core/workflow.py)):

- **VG-v2 (Search-Space-Gated)** — gating pindah ke *pertumbuhan pool*: reasoner
  bebas memilih retrieval presisi apa pun (seed / kombinasi / collaborative)
  untuk membentuk pool, lalu pool di-prune (top-12) + curate *shrink-only*.
  Menggantikan VG-v1 sebagai realisasi "Vector-Gated".
- **Planned (single-shot)** — skenario **ke-6**: 1 LLM call merencanakan seluruh
  urutan retrieval → eksekusi deterministik (tanpa loop ReAct) → 1 call sintesis.

Re-run **7 Juli 2026**, 100 query, GPU dedicated, `n=100 / 0 error`. Baris VG-v2
& Planned di matriks = konfigurasi **final audit-OFF** (`self_correct=False`;
A/B on/off & alasannya di [catatan_riset § 4.2](catatan_riset.md)).

### Matriks final (7 arm × 2 model)

| Skenario | Model | P@3 | P@5 | AnswCont | TitleFaith | TSM | Latency | DF |
|---|---|---|---|---|---|---|---|---|
| Standard RAG | Llama | 0.173 | 0.158 | 0.810 | 0.988 | – | 7.9s | 0 |
| Standard RAG | Qwen | 0.173 | 0.158 | 0.792 | 0.983 | – | 8.1s | 0 |
| CoT-RAG | Llama | 0.173 | 0.158 | 0.523 | 0.993 | – | 27.9s | 0 |
| CoT-RAG | Qwen | 0.173 | 0.158 | 0.882 | 0.965 | – | 26.1s | 0 |
| Act-only | Llama | 0.550 | 0.452 | 0.945 | 0.984 | 0.777 | 37.4s | 1 |
| Act-only | Qwen | 0.537 | 0.392 | 0.900 | 0.979 | 0.757 | 36.5s | 1 |
| Pure ReAct | Llama | 0.500 | 0.402 | 0.925 | 0.992 | 0.675 | 46.0s | 6 |
| Pure ReAct | Qwen | 0.483 | 0.364 | 0.835 | 0.977 | 0.642 | 46.3s | 3 |
| Vector-Gated **v1** (pre-fix) | Llama | 0.270 | 0.218 | 0.965 | 0.997 | 0.215 | 41.4s | 5 |
| Vector-Gated **v1** (pre-fix) | Qwen | 0.257 | 0.190 | 0.897 | 0.975 | 0.230 | 43.0s | 9 |
| **Vector-Gated v2** | Llama | **0.447** | 0.324 | 0.960 | 0.977 | **0.640** | **20.0s** | 8 |
| **Vector-Gated v2** | Qwen | **0.383** | 0.284 | 0.770 | 0.968 | **0.565** | **18.4s** | 7 |
| **Planned** 🏆 | Llama | **0.640** | 0.622 | 0.855 | 0.995 | 0.670 | **13.1s** | 3 |
| **Planned** 🏆 | Qwen | **0.713** | 0.680 | 0.865 | 0.945 | 0.677 | **13.1s** | 8 |

(Kolom & catatan kaki metrik — TitleFaith, TSM, DestrFilter — identik dengan
§ "5 Skenario Ablasi" di bawah.)

### P@3 per `hop_count` — arm agentic (Llama / Qwen)

| Arm | 1-hop | 2-hop | 3-hop |
|---|---|---|---|
| Act-only | 0.57 / 0.59 | 0.52 / 0.47 | 0.56 / 0.58 |
| Pure ReAct | 0.51 / 0.45 | 0.45 / 0.48 | 0.60 / 0.56 |
| Vector-Gated **v1** | 0.42 / 0.39 | 0.18 / 0.18 | **0.10 / 0.10** |
| Vector-Gated **v2** | 0.48 / 0.39 | 0.39 / 0.36 | **0.52 / 0.44** |
| **Planned** | 0.69 / 0.70 | 0.59 / 0.64 | **0.65 / 0.94** |

### Temuan

1. **VG-v2 memperbaiki keruntuhan multi-hop.** P@3 3-hop Llama **0.10 → 0.52**,
   TSM ~3× (0.215 → 0.640), **dan lebih cepat** (41.4s → 20.0s). Memindahkan
   penyempitan dari *melarang tool* ke *membatasi pertumbuhan pool* mengembalikan
   traversal multi-hop tanpa biaya latency — malah lebih hemat karena pool
   di-prune kecil.

2. **Planned mendominasi — dan mematahkan asumsi "butuh loop".** P@3 tertinggi
   dari semua arm (Qwen **0.713**, bahkan 3-hop Qwen **0.94**) **sekaligus**
   latency terendah (**~13s** kedua model). Single-shot planning mengalahkan setiap arm loop
   ReAct pada kualitas retrieval *dan* kecepatan. Implikasi: untuk task ini,
   loop reason⇄act per-step **tidak diperlukan** — retrieval cukup direncanakan
   sekali di depan lalu dieksekusi deterministik.

3. **Caveat — VG-v2 Qwen AnswCont masih di bawah v1** (v1 0.897 → v2 0.770):
   retrieval naik tapi `answer_contains` Qwen tetap turun dari v1 (sintesis atas
   pool presisi-tapi-berbeda menghasilkan lebih sedikit keyword expected) —
   perlu ditelusuri. Planned AnswCont 0.855–0.865 — di bawah Act-only (0.945)
   tapi dengan retrieval jauh lebih tinggi.

> **Grounding — self-correct dimatikan (A/B, 7 Juli)**: baris VG-v2 & Planned di
> matriks sudah pakai **audit-OFF** (`self_correct=False`, config final). A/B
> terkontrol on vs off ([catatan_riset.md § 4.2](catatan_riset.md)) menunjukkan
> responder self-correct **net-negatif**: dibanding OFF, run ON justru AC lebih
> rendah & latency +15–35%, **tanpa** gain faithfulness konsisten (P@3 identik —
> audit tak menyentuh retrieval). Audit deterministik (`_run_audit`) tetap jalan
> untuk observability; env `DISABLE_SELF_CORRECT` bisa kembalikan ON kalau perlu.

### Sumber file (7 Juli)

| Skenario (audit-OFF, config final) | Llama 3.1 8B | Qwen 2.5 7B |
|---|---|---|
| Vector-Gated v2 | `eval_results_agentic_llama_20260707_144026_noaudit.json` | `eval_results_agentic_qwen_20260707_151426_noaudit.json` |
| Planned | `eval_results_planned_llama31_20260707_154549_noaudit.json` | `eval_results_planned_qwen25_20260707_160812_noaudit.json` |

Pasangan **audit-ON** (tanpa `_noaudit`: `..._224831`, `..._233344`, `..._001021`,
`..._004022`) dipertahankan sebagai referensi A/B di [catatan_riset § 4.2](catatan_riset.md).
Arm lain (Standard/CoT/Act-only/Pure ReAct) tak berubah — baris **"Vector-Gated
ReAct"** di § "5 Skenario" di bawah = **VG-v1 (pre-fix)**.

---

## Ringkasan Hasil: 5 Skenario Ablasi × 2 Model (100 query)

Run **6 Juli 2026**, 100 query ground truth (Q01–Q100), **semua arm `n=100`,
`0 error`**. Ini metrik Phase 1 (offline); Phase 2 RAGAS/LLM-judge belum
dijalankan untuk grid ini. Definisi tiap metrik: lihat [`evaluasi.md`](evaluasi.md).

5 skenario = *ladder* ablasi ala paper ReAct (tiap baris menambah tepat satu
kapabilitas dibanding baris di atasnya):

| # | Skenario | `--pipelines` | Reason | Act (tool loop) | Gating |
|---|---|---|:---:|:---:|:---:|
| 1 | Standard RAG | `standard` | – | – | – |
| 2 | CoT-RAG | `cot` | ✓ | – | – |
| 3 | Act-only | `act_only` | – | ✓ | – |
| 4 | Pure ReAct | `pure_react` | ✓ | ✓ | – |
| 5 | Vector-Gated ReAct | `llama` / `qwen` | ✓ | ✓ | ✓ |

### Matriks metrik (Phase 1, offline)

| Skenario | Model | P@3 | P@5 | AnswCont | TitleFaith † | TSM ‡ | Latency | DestrFilter |
|---|---|---|---|---|---|---|---|---|
| Standard RAG | Llama 3.1 8B | 0.173 | 0.158 | 0.810 | 0.988 | – | 7.9s | 0 |
| Standard RAG | Qwen 2.5 7B | 0.173 | 0.158 | 0.792 | 0.983 | – | 8.1s | 0 |
| CoT-RAG | Llama 3.1 8B | 0.173 | 0.158 | **0.523** | 0.993 | – | 27.9s | 0 |
| CoT-RAG | Qwen 2.5 7B | 0.173 | 0.158 | **0.882** | 0.965 | – | 26.1s | 0 |
| Act-only | Llama 3.1 8B | 0.550 | 0.452 | 0.945 | 0.984 | 0.777 | 37.4s | 1 |
| Act-only | Qwen 2.5 7B | 0.537 | 0.392 | 0.900 | 0.979 | 0.757 | 36.5s | 1 |
| Pure ReAct | Llama 3.1 8B | 0.500 | 0.402 | 0.925 | 0.992 | 0.675 | 46.0s | 6 |
| Pure ReAct | Qwen 2.5 7B | 0.483 | 0.364 | 0.835 | 0.977 | 0.642 | 46.3s | 3 |
| Vector-Gated ReAct | Llama 3.1 8B | 0.270 | 0.218 | 0.965 | 0.997 | 0.215 | 41.4s | 5 |
| Vector-Gated ReAct | Qwen 2.5 7B | 0.257 | 0.190 | 0.897 | 0.975 | 0.230 | 43.0s | 9 |

> † **TitleFaith** = `title_faithfulness` (proxy offline: fraksi judul di jawaban
> yang benar-benar ada di konteks yang di-retrieve) — **bukan** Faithfulness
> LLM-judge di [Phase 2](#phase-2-llm-as-judge-faithfulness--answer-relevance)
> di bawah.
> ‡ **TSM** (`tool_set_match`) hanya bermakna untuk arm agentic; Standard RAG &
> CoT-RAG tidak pernah memanggil tool graph → skornya `0` *by design* (baca
> sebagai N/A, bukan kegagalan — lihat [`evaluasi.md`](evaluasi.md) § Arm Ablasi).
> **DestrFilter** = total `destructive_filter_calls` (argumen filter halusinasi
> yang akan mengosongkan pool kandidat).

### Temuan utama

1. **Efek reasoning eksplisit (CoT) berlawanan arah antar model** — dan hanya
   terlihat karena Standard RAG dijalankan **per-model** (retrieval-nya
   model-independent, tapi generation-nya tidak):
   - CoT-RAG(Llama) AC **0.523** vs Standard(Llama) **0.810** → reasoning
     eksplisit **menurunkan** AC Llama (−0.29).
   - CoT-RAG(Qwen) AC **0.882** vs Standard(Qwen) **0.792** → reasoning
     **menaikkan** AC Qwen (+0.09).
   - *Hipotesis*: Llama cenderung menghasilkan rantai penalaran panjang yang
     kurang patuh pada marker `JAWABAN AKHIR:`, sehingga ekstraksi jawaban
     final memburuk; Qwen lebih patuh format sehingga reasoning membantu.

2. **Sanity check retrieval lolos** — Standard RAG & CoT-RAG memberi
   P@3=0.173 / P@5=0.158 **identik** di keempat baris, karena retrieval
   keduanya vector top-5 yang sama (independen LLM). Semua selisih metrik di
   kedua arm ini murni efek generation, *by construction*.

3. **Acting yang menggerakkan retrieval, bukan reasoning** — arm dengan tool
   loop (Act-only, Pure ReAct) melonjak ke P@3 **0.48–0.55** (vs 0.173 pada
   arm tanpa acting). Traversal graph menambah recall judul relevan; reasoning
   saja (CoT) tidak menggeser P@K sama sekali.

4. **Channel `thought` tidak membantu, malah sedikit merugikan** — Act-only ≥
   Pure ReAct pada P@K, AC, dan TSM untuk **kedua** model, dengan DestrFilter
   lebih rendah (Llama 1 vs 6). Menambahkan interleaved CoT di dalam loop tidak
   menambah nilai pada task ini (prompt keduanya identik kecuali field
   `thought`).

5. **Vector-Gated: jawaban paling grounded, tapi recall retrieval turun** —
   router + phase-gating menghasilkan AC & TitleFaith tertinggi (AC Llama
   0.965, TitleFaith ~1.00) namun P@K & TSM lebih rendah dari Act-only/Pure
   ReAct. Gating memangkas eksplorasi tool (recall judul turun) demi jawaban
   yang lebih presisi-terhadap-konteks — trade-off *precision-of-answer* vs
   *breadth-of-retrieval*.

> Catatan pembacaan: banyak `query_type` hanya berisi 1–3 query, jadi
> perbedaan antar arm pada satu tipe adalah indikasi pola perilaku, bukan
> signifikansi statistik. Breakdown per tipe query / hop count:
> `python evaluation/analyze_by_query_type.py --latest`.

### Breakdown per kompleksitas (`hop_count`)

Rollup per jumlah hop (`n` lebih besar per kelompok → klaim lebih kuat
daripada per-`query_type` yang tiap tipe hanya 2–7 query). Kolom disusun
mengikuti *ladder* ablasi; nilai dikelompokkan per model.

> **Legenda kolom** — `Std`=Standard RAG, `CoT`=CoT-RAG, `Act`=Act-only,
> `PR`=Pure ReAct, `VG`=Vector-Gated ReAct · `L`=Llama 3.1 8B, `Q`=Qwen 2.5 7B.

**Precision@3**

| hop | n | Std·L | Std·Q | CoT·L | CoT·Q | Act·L | Act·Q | PR·L | PR·Q | VG·L | VG·Q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-hop | 42 | 0.21 | 0.21 | 0.21 | 0.21 | 0.57 | 0.59 | 0.51 | 0.45 | 0.42 | 0.39 |
| 2-hop | 42 | 0.15 | 0.15 | 0.15 | 0.15 | 0.52 | 0.47 | 0.45 | 0.48 | 0.18 | 0.18 |
| 3-hop | 16 | 0.12 | 0.12 | 0.12 | 0.12 | 0.56 | 0.58 | 0.60 | 0.56 | 0.10 | 0.10 |

**Answer Contains**

| hop | n | Std·L | Std·Q | CoT·L | CoT·Q | Act·L | Act·Q | PR·L | PR·Q | VG·L | VG·Q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-hop | 42 | 0.81 | 0.81 | 0.62 | 0.93 | 0.95 | 0.93 | 0.93 | 0.88 | 0.95 | 0.93 |
| 2-hop | 42 | 0.81 | 0.87 | 0.40 | 0.92 | 0.92 | 0.83 | 0.89 | 0.73 | 0.96 | 0.90 |
| 3-hop | 16 | 0.81 | 0.54 | 0.58 | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.79 |

**Tool Set Match** (Std & CoT tak pernah panggil tool → N/A)

| hop | n | Std·L | Std·Q | CoT·L | CoT·Q | Act·L | Act·Q | PR·L | PR·Q | VG·L | VG·Q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-hop | 42 | – | – | – | – | 0.80 | 0.83 | 0.71 | 0.71 | 0.38 | 0.38 |
| 2-hop | 42 | – | – | – | – | 0.71 | 0.62 | 0.59 | 0.51 | 0.13 | 0.17 |
| 3-hop | 16 | – | – | – | – | 0.88 | 0.94 | 0.81 | 0.81 | 0.00 | 0.00 |

**Bacaan breakdown:**

- **Vector-Gated ambruk saat kompleksitas naik.** P@3 VG jatuh
  `0.42 → 0.18 → 0.10` (Llama) dan `0.39 → 0.18 → 0.10` (Qwen) dari 1→3 hop,
  padahal Act-only & Pure ReAct **bertahan di ~0.5+** di semua tingkat hop.
  Phase-gating yang harusnya menstabilkan justru **memangkas eksplorasi tool**
  untuk query multi-hop — VG malah jadi arm agentic **terlemah** di retrieval
  multi-hop, walau AC-nya (generation) tetap tinggi.
- **TSM VG turun ke 0.00 di 3-hop** — router/gating memilih tool yang makin
  menyimpang dari `expected_tools` saat rantai bertambah panjang; Act-only
  malah **naik** (0.88/0.94) di 3-hop.
- **Efek CoT model-dependent makin jelas di multi-hop** — CoT·L AC anjlok ke
  **0.40** di 2-hop (reasoning tanpa acting kewalahan), sedangkan CoT·Q
  bertahan **0.92**. Konsisten dengan temuan #1 di atas.
- Semua arm non-acting (Std, CoT) flat di P@3 `0.21→0.15→0.12` — tanpa
  traversal graph, retrieval tak bisa mengejar kebutuhan multi-hop.

Breakdown lengkap **per-`query_type`** (22 tipe × 5 metrik, termasuk P@5 &
latency) tersimpan di
[`evaluation/hasil_eval/breakdown_per_query_type_20260706.md`](../evaluation/hasil_eval/breakdown_per_query_type_20260706.md)
(+ `.csv` long-format), atau regen kapan saja dengan
`python evaluation/analyze_by_query_type.py --latest`.

### Sumber file (reproducibility)

Diambil dari `latest-per-(pipeline, model)` di `evaluation/hasil_eval/`:

| Skenario | Llama 3.1 8B | Qwen 2.5 7B |
|---|---|---|
| Standard RAG | `eval_results_standard_20260706_081128.json` | `eval_results_standard_20260706_112205.json` |
| CoT-RAG | `eval_results_cot_rag_llama31_20260706_015432.json` | `eval_results_cot_rag_qwen25_20260706_050120.json` |
| Act-only | `eval_results_act_only_llama31_20260706_015432.json` | `eval_results_act_only_qwen25_20260706_050120.json` |
| Pure ReAct | `eval_results_pure_react_llama31_20260706_015432.json` | `eval_results_pure_react_qwen25_20260706_050120.json` |
| Vector-Gated ReAct | `eval_results_agentic_llama_20260706_082510.json` | `eval_results_agentic_qwen_20260706_093444.json` |

---

## Phase 1: Offline Metrics (Precision@K, Answer Contains, Tool Set Match, Latency, Tokens)

> ℹ️ Bagian di bawah ini adalah run **eksplorasi awal** (30 query, 3 pipeline)
> sebelum grid ablasi lengkap di atas. Dipertahankan sebagai jejak riset;
> untuk hasil terkini pakai ringkasan 100-query di atas.

Contoh output terminal dari `python evaluation/run_comparative_evaluation.py`
(30 query, semua 3 pipeline):

```
======================================================================
  COMPARATIVE EVALUATION
  Queries: 30  |  Precision@K: K=5
  Llama model : llama3.1:8b
  Qwen model  : qwen2.5:7b
======================================================================

──────────────────────────────────────────────────────────────────────
  Pipeline : Agentic GraphRAG (Llama) [llama3.1:8b]
  Queries  : 30  |  Output: eval_results_agentic_llama_20260628_204516.json
──────────────────────────────────────────────────────────────────────
[ 1/30] Q01 — Rekomendasikan buku karya Tere Liye yang tersed... ✅ P@5=0.40  AC=1.00  TSM=1.00  (12s)
[ 2/30] Q02 — Cari buku agama Islam yang tersedia di perpust... ✅ P@5=0.20  AC=0.67  TSM=1.00  (9s)
...

  ✓ Avg P@5=0.32  AC=0.78  TSM=0.85  Lat=11.2s  → eval_results_agentic_llama_20260628_204516.json

================================================================================
  OFFLINE METRICS SUMMARY (Phase 1 of 2)
================================================================================
  Pipeline                               | P@3   | P@5   | AnswCont |  TSM   | Lat(s) | Tokens | Err
  ---------------------------------------+--------+--------+----------+--------+--------+--------+----
  Standard RAG                           | 0.2667 | 0.2733 | 0.7278   | 0.0000 |   4.8s |  38236 | 0
  Agentic GraphRAG (llama3.1:8b)         | 0.2444 | 0.2133 | 0.4000   | 0.8889 |  18.9s | 178275 | 0
  Agentic GraphRAG (qwen2.5:7b)          | 0.2444 | 0.2133 | 0.4000   | 0.8889 |  18.7s | 178272 | 0

  Phase 2 (RAGAS Faithfulness + Answer Relevance):
    python evaluation/ragas_evaluation.py
  (atau --use-groq untuk pakai Groq sebagai judge LLM)
```

Run ini di 30 query (Q01–Q30), sebelum ekspansi ground truth ke 100 query
— lihat [`evaluasi.md`](evaluasi.md) untuk definisi tiap metrik.

---

## Phase 2: LLM-as-Judge (Faithfulness & Answer Relevance)

> ⚠️ **Judge = Claude Sonnet 5 (protokol manual/interaktif), bukan
> `ragas_evaluation.py` otomatis via Groq/OpenAI** — tidak ada akses API
> credit untuk judge model saat evaluasi ini dijalankan, jadi skor di
> bawah dinilai langsung di sesi chat, bukan lewat pipeline RAGAS yang
> didesain di `evaluasi.md`. Baca
> [catatan_riset.md § 9](catatan_riset.md#9-catatan-metodologi-phase-2-dijalankan-manual-claude-sebagai-judge-bukan-ragasdeepeval-otomatis-via-api)
> untuk limitasi lengkap (judge model berbeda dari desain, algoritma
> holistik vs dekomposisi klaim RAGAS, tidak blind, tidak reproducible
> ketat, tanpa inter-rater check) sebelum mengutip angka ini sebagai hasil
> "RAGAS".

Hasil judging Phase 2 untuk 30 query (Q01–Q30) pada ketiga pipeline,
dievaluasi terhadap `answer`, `contexts`, dan `reference_answer` dari
masing-masing `eval_results_*.json`.

### Ringkasan

| Pipeline | Avg Faithfulness | Avg Answer Relevance |
|---|---|---|
| Standard RAG | 0.78 | 0.48 |
| Agentic GraphRAG (Llama 3.1 8B) | 0.44 | 0.44 |
| Agentic GraphRAG (Qwen 2.5 7B) | 0.97 | 0.41 |

**Temuan utama**: sebagian besar query pada kedua pipeline agentic
mengembalikan `contexts` **kosong** (tidak ada retrieval yang terjadi) —
16/30 pada Llama dan Qwen. Ini membuat Faithfulness tinggi (tidak ada
yang di-hallucinate karena jawabannya jujur "tidak ditemukan") tapi
Answer Relevance rendah (reference_answer menunjukkan bahwa hasil
sebenarnya ada, tapi tidak pernah berhasil diambil). Standard RAG tidak
pernah mengembalikan contexts kosong, tetapi sering mengarang `book_id`
yang tidak ada di context manapun, sehingga faithfulness-nya tertahan
di kisaran 0.5–0.9 bukan mendekati 1.0.

Pola contexts kosong ini kemungkinan merupakan bug retrieval/tool
execution pada agentic pipeline, terpisah dari kualitas generasi
jawaban yang diukur di sini — perlu investigasi lebih lanjut pada
`agent/tools/` dan `agent/nodes/tool_executor.py`.

<details>
<summary><strong>Detail per query — Standard RAG</strong></summary>

| Query ID | Faithfulness (0-1) | Answer Relevance (0-1) | Brief Justification |
|---|---|---|---|
| Q01 | 0.65 | 0.6 | Titles/vibes match context but invented book IDs not in contexts; missed several Tere Liye titles. |
| Q02 | 0.9 | 0.4 | Title/vibe/category faithful to context; only 1 of many thriller books, narrow coverage. |
| Q03 | 0.85 | 0.5 | Both titles/settings accurate from context; invented IDs; only 2 of 97 books, thin coverage. |
| Q04 | 0.85 | 0.5 | Titles match context generally; vague justification; only 2 of 156 books. |
| Q05 | 0.95 | 0.6 | Title/category/ID accurate from context; only 1 of 96 matching books. |
| Q06 | 0.9 | 0.3 | Correctly notes no explicit "English" label, but several titles are clearly English-language; under-delivers vs query intent. |
| Q07 | 0.6 | 0.6 | Naura linked correctly to 2 books, but numbering/synopsis paraphrase slightly off. |
| Q08 | 0.9 | 0.2 | Faithful refusal (no Surabaya publisher info in context) but fails query intent vs 16 known matches. |
| Q09 | 0.95 | 0.45 | Ceros Dan Batozar faithfully matches vibe+setting; only 1 of 25 books surfaced. |
| Q10 | 0.5 | 0.5 | Cites vibe correctly but mislabels as recommendation despite weak match; thin coverage. |
| Q11 | 0.85 | 0.55 | 3 titles match category/vibe faithfully; invented numbering; partial coverage. |
| Q12 | 0.55 | 0.4 | Vibe is misteri/horor not literally "thriller"; loose inference; thin coverage (1 of 20). |
| Q13 | 0.9 | 0.55 | Both titles/settings/categories accurate from context; invented IDs; only 2 of 22 books. |
| Q14 | 0.85 | 0.6 | Both correctly vibe-matched; invented IDs; missing several known titles. |
| Q15 | 0.95 | 0.15 | Correct refusal given context lacks the author entirely; fails query intent vs 13 known matches. |
| Q16 | 0.85 | 0.85 | All 5 titles faithfully drawn from context as Tere Liye novels; invented IDs; good coverage. |
| Q17 | 0.85 | 0.5 | Title/category/branch faithful to context; only 1 of 25 relevant books surfaced. |
| Q18 | 0.85 | 0.55 | Correctly flags no "monograf" term but lists matching titles faithfully; partial coverage. |
| Q19 | 0.6 | 0.3 | Roughly faithful but admits unknown vibe, weak match; only 1 of 15 relevant books. |
| Q20 | 0.55 | 0.35 | Cited book's setting mismatches query intent. |
| Q21 | 0.85 | 0.55 | Title/setting reasonably faithful; only 1 of 15 relevant books surfaced. |
| Q22 | 0.8 | 0.7 | Multiple context titles with accurate vibe details; rambling but on-topic; invented ID. |
| Q23 | 0.85 | 0.6 | Both cited books faithfully reflect theme from context; reasonably on-topic. |
| Q24 | 0.2 | 0.15 | Claims no similar-DDC book exists despite context showing 4 dinosaur-category books; contradicts context. |
| Q25 | 0.5 | 0.7 | Titles match context but invented IDs not present anywhere; on-topic similarity answer. |
| Q26 | 0.9 | 0.2 | Faithful refusal since exact title absent from context; fails to leverage near-matches. |
| Q27 | 0.9 | 0.2 | Faithful refusal; fails to suggest closely related books. |
| Q28 | 0.85 | 0.55 | Titles/branch faithfully match context vibe (loosely "thriller"); invented IDs; thin coverage. |
| Q29 | 0.85 | 0.85 | Titles, branch, and IDs partially align with context; good coverage. |
| Q30 | 0.75 | 0.5 | Titles/branch generally match context but invented IDs; thin coverage. |
| **Average Faithfulness** | **0.78** | | |
| **Average Answer Relevance** | | **0.48** | |

</details>

<details>
<summary><strong>Detail per query — Agentic GraphRAG (Llama 3.1 8B)</strong></summary>

| Query ID | Faithfulness (0-1) | Answer Relevance (0-1) | Brief Justification |
|---|---|---|---|
| Q01 | 0.95 | 0.9 | Titles, authors, vibes, branches all match contexts exactly; relevant author+city recs. |
| Q02 | 0.0 | 0.1 | Empty contexts, generic "not found" fallback; reference shows 97 matches existed. |
| Q03 | 0.0 | 0.1 | Empty contexts, generic fallback; query unanswered despite 97 matches in reference. |
| Q04 | 0.95 | 0.85 | All titles/authors/vibes/branches trace to contexts; relevant child-category recs. |
| Q05 | 0.95 | 0.85 | Titles, authors, categories, branches accurately drawn from contexts. |
| Q06 | 0.0 | 0.1 | Empty contexts, generic fallback despite 76 English books existing per reference. |
| Q07 | 0.95 | 0.85 | Book details faithfully match contexts. |
| Q08 | 0.0 | 0.1 | Empty contexts, generic fallback despite 16 Surabaya-publisher books in reference. |
| Q09 | 0.0 | 0.1 | Empty contexts, generic fallback despite 25 matching books in reference. |
| Q10 | 0.0 | 0.1 | Empty contexts, generic fallback despite 23 matching novels in reference. |
| Q11 | 0.95 | 0.9 | Titles, vibes, settings, branches accurately sourced from contexts; relevant romance recs. |
| Q12 | 0.0 | 0.1 | Empty contexts, generic fallback despite 20 matching books in reference. |
| Q13 | 0.95 | 0.9 | Book details faithfully reflect contexts for kingdom-setting novels. |
| Q14 | 0.95 | 0.9 | Titles/vibes/branches match contexts; relevant Tere Liye adventure recommendations. |
| Q15 | 0.9 | 0.6 | Correctly admits no author match; suggested books faithful but off-target. |
| Q16 | 0.95 | 0.9 | Titles, authors, branches match contexts; directly answers Tere Liye novel query. |
| Q17 | 0.95 | 0.95 | Titles, categories, branches all match contexts; directly answers query. |
| Q18 | 0.0 | 0.1 | Empty contexts, generic fallback despite 62 matching books in reference. |
| Q19 | 0.0 | 0.1 | Empty contexts, generic fallback despite 15 matching novels in reference. |
| Q20 | 0.0 | 0.1 | Empty contexts, generic fallback despite 15 matching novels in reference. |
| Q21 | 0.9 | 0.55 | Faithful to contexts but recs only loosely match "rumah" setting. |
| Q22 | 0.0 | 0.1 | Empty contexts, generic fallback; similarity query unanswered. |
| Q23 | 0.0 | 0.1 | Empty contexts, generic fallback; similarity query unanswered. |
| Q24 | 0.9 | 0.85 | Titles/authors/branches match contexts; reasonable DDC-similarity recs. |
| Q25 | 0.0 | 0.1 | Empty contexts, generic fallback; similarity query unanswered. |
| Q26 | 0.0 | 0.1 | Empty contexts, generic fallback; similarity query unanswered. |
| Q27 | 0.0 | 0.1 | Empty contexts, generic fallback; similarity query unanswered. |
| Q28 | 0.0 | 0.1 | Empty contexts, generic fallback despite 20 matching thrillers in reference. |
| Q29 | 0.95 | 0.95 | Titles, vibes, settings, branches all match contexts; precisely answers query. |
| Q30 | 0.9 | 0.75 | Faithful to contexts but only partial family-theme coverage. |
| **Average Faithfulness** | **0.44** | | |
| **Average Answer Relevance** | | **0.44** | |

</details>

<details>
<summary><strong>Detail per query — Agentic GraphRAG (Qwen 2.5 7B)</strong></summary>

| Query ID | Faithfulness (0-1) | Answer Relevance (0-1) | Brief Justification |
|---|---|---|---|
| Q01 | 0.97 | 0.9 | All titles/branches/vibes match contexts; directly answers author+city query. |
| Q02 | 1.0 | 0.05 | Empty contexts, honest fallback; fails to surface the 97 matches that exist. |
| Q03 | 1.0 | 0.05 | Empty contexts, fallback; reference shows matches existed but none surfaced. |
| Q04 | 0.95 | 0.85 | Titles/authors/vibes/branches grounded in contexts; addresses request well. |
| Q05 | 0.95 | 0.85 | Books, categories, branches match contexts; answers query directly. |
| Q06 | 1.0 | 0.05 | Empty contexts, honest fallback; 76 English books existed per reference but not retrieved. |
| Q07 | 0.9 | 0.75 | Books/vibes/branches grounded; mostly on-topic, some tangential matches. |
| Q08 | 1.0 | 0.05 | Empty contexts, fallback; reference shows matches existed. |
| Q09 | 1.0 | 0.05 | Empty contexts, fallback despite 25 matching books existing per reference. |
| Q10 | 1.0 | 0.05 | Empty contexts, fallback despite 23 matching novels existing per reference. |
| Q11 | 0.95 | 0.9 | Titles, vibes, locations match contexts; directly answers query. |
| Q12 | 1.0 | 0.05 | Empty contexts, fallback despite 20 matching books existing. |
| Q13 | 0.95 | 0.85 | Titles/vibes/latar/branches grounded; addresses setting query well. |
| Q14 | 0.95 | 0.9 | All books genuinely match per contexts; directly relevant. |
| Q15 | 0.95 | 0.4 | Honest about no author match; grounded but doesn't fulfill the actual ask. |
| Q16 | 0.95 | 0.9 | Titles/branches grounded in contexts; directly lists asked novels. |
| Q17 | 0.97 | 0.95 | Titles/categories/branch all match contexts; precisely answers query. |
| Q18 | 1.0 | 0.05 | Empty contexts, fallback despite 62 matching books existing. |
| Q19 | 1.0 | 0.05 | Empty contexts, fallback despite 15 matching novels existing. |
| Q20 | 1.0 | 0.05 | Empty contexts, fallback despite 15 matching novels existing. |
| Q21 | 0.85 | 0.65 | Mostly grounded; framing slightly stretched. |
| Q22 | 1.0 | 0.05 | Empty contexts, fallback despite similar-vibe books existing. |
| Q23 | 1.0 | 0.05 | Empty contexts, fallback despite similar-vibe books existing. |
| Q24 | 0.95 | 0.85 | Titles/categories grounded in contexts; correctly addresses similarity request. |
| Q25 | 1.0 | 0.05 | Empty contexts, fallback despite similar books existing. |
| Q26 | 1.0 | 0.05 | Empty contexts, fallback despite similar books existing. |
| Q27 | 1.0 | 0.05 | Empty contexts, fallback despite similar accounting books existing. |
| Q28 | 1.0 | 0.05 | Empty contexts, fallback despite 20 thrillers at that branch existing. |
| Q29 | 0.92 | 0.9 | Titles/vibes/branch grounded; directly answers query, minor omissions. |
| Q30 | 0.92 | 0.8 | Titles/branch grounded; reasonably answers query, slight stretch. |
| **Average Faithfulness** | **0.97** | | |
| **Average Answer Relevance** | | **0.41** | |

</details>
