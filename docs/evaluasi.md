# Evaluasi & Metrik

## Gambaran Umum

Sistem evaluasi menggunakan **6-metric hybrid framework** yang dirancang
khusus untuk sistem rekomendasi buku — di mana tidak ada satu jawaban
absolut yang "benar". Framework ini menggabungkan tiga kategori metrik:

1. **Retrieval** — mengukur kualitas pencarian
2. **Generation (RAGAS / LLM-as-a-Judge)** — mengukur kualitas jawaban
3. **Operational Agent** — mengukur efisiensi dan perilaku agent

Evaluasi dijalankan dalam **dua fase** terpisah:

| Fase | Script | Metrik | Butuh API Key? |
|------|--------|--------|----------------|
| Phase 1 (offline) | `evaluation/run_comparative_evaluation.py` | Precision@K, Latency, Token Cost, Tool Set Match, Answer Contains | ❌ Tidak |
| Phase 2 (LLM judge) | `evaluation/ragas_evaluation.py` | Faithfulness, Answer Relevance | ✅ Groq atau OpenAI |

### Kenapa Hybrid?

Sistem rekomendasi buku berbeda dari factoid QA:

- **Tidak ada satu jawaban benar** — beberapa rekomendasi bisa sama-sama valid
- **Tool call order bervariasi** — agent boleh memanggil tool dalam urutan berbeda
- **Faithfulness perlu LLM judge** — tidak bisa diukur hanya dengan keyword matching

Maka kita menggunakan campuran metrik deterministik (offline) dan LLM-as-a-judge.

---

## Ground Truth

**File**: `evaluation/ground_truth.json`

Berisi 100 query (Q01–Q100) dengan berbagai tipe dan hop count. Q01–Q30
adalah batch awal (kurasi manual); Q31–Q100 dihasilkan terprogram langsung
dari data graph gold (`data_pipeline/gold/graph/*.json`) — lihat
[§ Metodologi Generasi Q31–Q100](#metodologi-generasi-q31q100) di bawah
untuk detail cara tiap angka/`book_id`/`expected_titles` dihitung (bukan
dikarang manual).

```json
{
  "id": "Q29",
  "query": "Buku karya Tere Liye yang tersedia di Perpustakaan Jakarta Pusat - Petojo Enclek",
  "query_type": "branch_filter_author",
  "hop_count": 2,
  "expected_tools": ["books_by_author", "filter_by_branch"],
  "expected_titles": [
    "#About Love", "#AboutFriends", "Berjuta Rasanya", "..."
  ],
  "expected_answer_contains": ["Tere Liye", "Petojo Enclek"],
  "reference_answer": "Ada 15 buku Tere Liye tersedia di Perpustakaan Jakarta Pusat - Petojo Enclek..."
}
```

`expected_tools` diisi untuk **semua** 22 `query_type` — setiap tipe punya
padanan 1:1 ke satu (atau dua) tool deterministik di
[`agent/tools/tools_catalog.py`](../agent/tools/tools_catalog.py), jadi
`tool_set_match` (lihat [Metrik 6](#metrik-6-operational--tool-set-match))
bisa dihitung untuk seluruh 100 query, bukan cuma subset yang punya tool
"jelas". Mapping lengkapnya ada di
[§ Query-Type → Tool Mapping](#query-type--tool-mapping) di bawah.

`expected_titles` berisi daftar string judul buku — evaluasi dilakukan dengan 
mencocokkan judul secara *case-insensitive*. Ini menghindari kebingungan id unik, karena
satu judul buku bisa punya beberapa `book_id` berbeda (edisi/eksemplar berbeda).

### Tipe Query yang Dievaluasi

22 `query_type` berbeda di 100 query, masing-masing diawali jumlah hop:

| Tipe | Contoh | Hop Count |
|------|--------|-----------|
| `1-hop_author` | "Rekomendasikan buku karya Tere Liye yang tersedia di perpustakaan Jakarta" | 1 |
| `1-hop_vibe` | "Carikan buku dengan nuansa thriller yang mendebarkan" | 1 |
| `1-hop_setting` | "Aku ingin baca novel yang berlatar kerajaan" | 1 |
| `1-hop_category` | "Rekomendasikan buku kategori Cerita Anak untuk anak saya" | 1 |
| `1-hop_ddc` | "Ada buku dengan klasifikasi DDC 641 soal kuliner dan masakan?" | 1 |
| `1-hop_language` | "Carikan buku yang ditulis dalam bahasa Inggris" | 1 |
| `1-hop_character` | "Apakah ada buku dengan tokoh Naura?" | 1 |
| `1-hop_publisher_city` | "Saya cari buku terbitan penerbit yang berlokasi di Surabaya" | 1 |
| `2-hop_vibe_setting` | "Cari buku bernuansa petualangan yang berlatar pedesaan" | 2 |
| `2-hop_vibe_category` | "Carikan buku bernuansa romance dalam kategori Fiksi" | 2 |
| `2-hop_setting_category` | "Cari novel Fiksi Indonesia yang berlatar kerajaan" | 2 |
| `2-hop_author_vibe` | "Buku karya Tere Liye yang bertema petualangan" | 2 |
| `2-hop_author_setting` | "Buku karya Nurhadiansyah yang berlatar di rumah" | 2 |
| `2-hop_author_category` | "Novel karya Tere Liye apa saja yang ada di perpustakaan?" | 2 |
| `2-hop_ddc_branch` | "Ada buku DDC 371 soal pendidikan di Perpustakaan Jakarta - Kuningan?" | 2 |
| `2-hop_collectiontype_category` | "Carikan buku jenis monograf kategori Motivasi" | 2 |
| `3-hop_vibe_setting_category` | "Cari novel romance berlatar sekolah dalam kategori Novel" | 3 |
| `collaborative_shared_vibe` | "Ada buku lain dengan nuansa serupa \"101 Resep Kue Kering Klasik & Modern\"?" | 3 |
| `collaborative_shared_ddc` | "Ada buku lain dengan klasifikasi DDC yang sama dengan \"Ensiklopedia Visual Dinosaurus\"?" | 3 |
| `runtime_similarity` | "Carikan buku yang mirip dengan \"Seri Cerita Balita : Aku Sayang Teman\"" | 1 |
| `branch_filter_vibe` | "Buku thriller apa yang tersedia di Perpustakaan Jakarta Barat - Tanjung Duren?" | 2 |
| `branch_filter_author` | "Buku karya Tere Liye yang tersedia di Perpustakaan Jakarta Pusat - Petojo Enclek" | 2 |

### Query-Type → Tool Mapping

Setiap `query_type` di ground truth punya padanan 1:1 ke tool di
[`agent/tools/tools_catalog.py`](../agent/tools/tools_catalog.py) — tool
itulah yang **seharusnya** dipanggil reasoner untuk menjawab query tipe
tersebut, dan jadi acuan `expected_tools` yang dinilai `tool_set_match`
([Metrik 6](#metrik-6-operational--tool-set-match)):

| `query_type` | `expected_tools` | Tool ini di catalog melakukan apa |
|---|---|---|
| `1-hop_author` | `books_by_author` | `(:Author)-[:WROTE]->(:Book)`, filter nama author |
| `1-hop_vibe` | `books_by_vibe` | `(:Book)-[:HAS_VIBE]->(:Vibe)`, filter nama vibe |
| `1-hop_setting` | `books_by_setting` | `(:Book)-[:HAS_SETTING]->(:Setting)`, filter nama setting |
| `1-hop_category` | `books_by_category` | `(:Book)-[:BELONGS_TO]->(:Category)`, filter nama kategori |
| `1-hop_ddc` | `books_by_ddc` | `(:Book)-[:CLASSIFIED_AS]->(:DDCClass)`, filter `code STARTS WITH` prefix |
| `1-hop_language` | `books_by_language` | `(:Book)-[:WRITTEN_IN]->(:Language)`, filter nama bahasa |
| `1-hop_character` | `books_by_character` | `(:Book)-[:FEATURES_CHARACTER]->(:Character)`, filter nama tokoh |
| `1-hop_publisher_city` | `books_by_publisher_city` | `(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)`, filter nama kota |
| `2-hop_vibe_setting` | `books_by_vibe_and_setting` | Intersection `HAS_VIBE` ∩ `HAS_SETTING` pada `Book` yang sama |
| `2-hop_vibe_category` | `books_by_vibe_and_category` | Intersection `HAS_VIBE` ∩ `BELONGS_TO` |
| `2-hop_setting_category` | `books_by_setting_and_category` | Intersection `HAS_SETTING` ∩ `BELONGS_TO` |
| `2-hop_author_vibe` | `books_by_author_and_vibe` | Intersection `WROTE` ∩ `HAS_VIBE` |
| `2-hop_author_setting` | `books_by_author_and_setting` | Intersection `WROTE` ∩ `HAS_SETTING` |
| `2-hop_author_category` | `books_by_author_and_category` | Intersection `WROTE` ∩ `BELONGS_TO` |
| `2-hop_ddc_branch` | `books_by_ddc_and_branch` | Intersection `CLASSIFIED_AS` (prefix) ∩ `AVAILABLE_AT` |
| `2-hop_collectiontype_category` | `books_by_collection_type_and_category` | Intersection `COLLECTION_TYPE` ∩ `BELONGS_TO` |
| `3-hop_vibe_setting_category` | `books_by_vibe_and_setting_and_category` | Triple intersection `HAS_VIBE` ∩ `HAS_SETTING` ∩ `BELONGS_TO` |
| `collaborative_shared_vibe` | `books_sharing_vibe_with` | Buku lain yang berbagi **minimal satu** `HAS_VIBE` dengan buku referensi (title match), diurutkan berdasar jumlah vibe yang sama |
| `collaborative_shared_ddc` | `books_sharing_ddc_with` | Buku lain dengan `CLASSIFIED_AS` **sama persis** (kode DDC identik) dengan buku referensi |
| `runtime_similarity` | `search_similar_runtime` | KNN embedding (`book_vector_index`, cosine) atas `Book.embedding`, top-K tetangga terdekat dari buku referensi |
| `branch_filter_vibe` | `books_by_vibe_and_branch` | Single-query intersection `HAS_VIBE` ∩ `AVAILABLE_AT` (dipilih daripada `books_by_vibe` + `filter_by_branch` dua langkah — lihat docstring tool ini di catalog: pool vibe umum yang di-filter branch belakangan cenderung kolaps ke 0) |
| `branch_filter_author` | `books_by_author`, `filter_by_branch` | Dua langkah: seed by author lalu narrow by branch. Tidak ada tool gabungan (`books_by_author_and_branch`) karena pool per-author di dataset ini sudah kecil (≤23 buku) — risiko kolaps-ke-0 yang dialami `books_by_vibe_and_branch` tidak berlaku di sini |

### Metodologi Generasi Q31–Q100

Q31–Q100 dihasilkan oleh script sekali-pakai yang membaca langsung
`data_pipeline/gold/graph/*.json` (bukan Neo4j — file gold JSON yang sama
yang di-*ingest* ke database) dan menghitung ground truth secara
programatik, per `query_type`:

1. **1-hop / 2-hop / 3-hop** (`author`, `vibe`, `setting`, `category`,
   `ddc`, `language`, `character`, `publisher_city`, `collection_type`,
   `branch`): dibangun dari **set intersection** relasi mentah
   (`rels_vibe.json`, `rels_setting.json`, `rels_category.json`, dst.) —
   identik dengan operasi `MATCH ... WHERE ...` di Cypher tool yang
   berpadanan pada tabel di atas. Entitas dipilih dari kombinasi yang
   *belum* dipakai di Q01–Q30 dan menghasilkan `3 ≤ jumlah_buku ≤ 160`
   (rentang yang sama dengan Q01–Q30, agar contoh tetap representatif dan
   file tidak membengkak).
2. **`collaborative_shared_vibe`**: dipilih buku referensi lalu dihitung
   `{b : b ≠ ref, HAS_VIBE(b) ∩ HAS_VIBE(ref) ≠ ∅}` — union match (buku
   manapun yang berbagi *minimal satu* vibe), sama persis dengan logika
   `books_sharing_vibe_with`. Divalidasi terhadap Q23 (contoh dari batch
   manual Q01–Q30) sebelum dipakai: hasil hitung terprogram (11 buku)
   cocok 100% dengan `expected_titles` Q23 yang sudah ada.
3. **`collaborative_shared_ddc`**: `{b : b ≠ ref, ddc_code(b) = ddc_code(ref)}`
   — exact match kode DDC. Divalidasi serupa terhadap Q24 (10 buku, cocok
   100%).
4. **`runtime_similarity`**: cosine similarity antar vektor
   `Book.embedding` (field yang sudah ada di `nodes_book.json`, dipakai
   ulang — bukan di-generate ulang), top-5 tetangga terdekat selain buku
   itu sendiri. Divalidasi terhadap Q25: top-5 hasil hitung terprogram
   cocok persis dengan `expected_titles` Q25 (termasuk urutan setelah
   di-sort alfabetis).
5. **`branch_filter_vibe` / `branch_filter_author`**: intersection
   `AVAILABLE_AT` dengan set hasil vibe/author.

Setiap entry lalu menghasilkan:
- `reference_answer`: template `"Ada {n} buku {atribut}, contohnya: {t1}
  ({id1}), {t2} ({id2}), {t3} ({id3})."` — 3 contoh pertama setelah
  `expected_titles` di-*sort* alfabetis (string sort Python default,
  termasuk kasus edge seperti anomali spasi-ganda pada judul sumber, yang
  memengaruhi urutan sort dan sudah diverifikasi cocok dengan pola Q25).
- `expected_titles`: **seluruh** judul yang match (tidak dipotong ke
  top-K) — jumlahnya bisa melebihi `LIMIT 15` di dalam Cypher tool
  (mis. `1-hop_vibe` "sejarah" → 143 judul, sementara `books_by_vibe`
  sendiri `LIMIT 15` per panggilan). Ini konsisten dengan pola Q01–Q30
  (mis. Q05 punya 96 `expected_titles` walau `books_by_ddc` juga
  `LIMIT 15`) — `expected_titles` merepresentasikan *universe* buku yang
  relevan untuk Precision@K/recall, bukan output satu kali panggilan tool.

Script generator tidak disimpan permanen di repo (dijalankan sekali dari
scratchpad); logika di atas cukup untuk mereproduksi hasil yang sama dari
`data_pipeline/gold/graph/*.json` kapan saja bila perlu query tambahan.

---

## Metrik 1: Retrieval — Precision@K

**Kategori**: Retrieval | **Fase**: Phase 1 (offline)

```
Precision@K = |retrieved[:K] ∩ expected| / K
```

Mengukur proporsi dari top-K buku yang diambil yang benar-benar ada di
ground truth `expected_titles`.

Untuk sistem rekomendasi: `expected_titles` berfungsi sebagai "relevant
set" (bukan satu jawaban tunggal). Query yang `expected_titles`-nya
kosong (mis. query vibe+setting yang hasilnya subjektif) dikecualikan
dari perhitungan rata-rata.

> ⚠️ **Frame eksplisit sebagai lower-bound proxy, bukan angka presisi
> mutlak.** `expected_titles` adalah *sample* kurasi manual dari
> `evaluation/ground_truth.json`, bukan daftar exhaustive dari semua buku
> yang valid buat suatu query. Rekomendasi yang sebetulnya relevan tapi
> tidak masuk sample itu tetap dihitung "salah" oleh formula di atas —
> jadi Precision@K **meremehkan (underestimate)** presisi sebenarnya,
> nggak pernah melebih-lebihkannya. Berguna buat membandingkan pipeline
> secara relatif (apple-to-apple, sample ground truth yang sama), tapi
> JANGAN dibaca sebagai "sistem ini X% benar" secara absolut. Metrik
> LLM-as-Judge (Faithfulness/Answer Relevance, § Metrik 2–3 di bawah)
> tidak kena bias ini karena nge-judge grounding & relevansi jawaban,
> bukan exact-match judul terhadap sample yang terbatas — jadikan itu
> sinyal utama buat correctness, Precision@K sinyal sekunder/sanity-check.
> (Lihat juga [catatan_riset.md § 7](catatan_riset.md#7-yang-belum-diputuskan--opsi-simplifikasi-yang-masih-didiskusikan).)

**Implementasi**: [`evaluation/metrics.py → precision_at_k()`](../evaluation/metrics.py)

---

## Metrik 2–3: Generation (RAGAS / LLM-as-a-Judge)

**Kategori**: Generation | **Fase**: Phase 2 (LLM judge)

### Faithfulness

Mengukur apakah klaim dalam jawaban akhir **sepenuhnya didukung** oleh
konteks yang diambil. Mendeteksi:
- Sinopsis yang dikarang (hallucinated)
- Ketersediaan buku palsu
- Penulis yang salah

RAGAS melakukan ini dengan mengekstrak claims dari jawaban, lalu
memverifikasi tiap claim terhadap konteks menggunakan LLM judge.

### Answer Relevance

Mengukur seberapa baik jawaban akhir **menjawab pertanyaan** pengguna.
RAGAS menghitung ini dengan:
1. Generate beberapa pertanyaan dari jawaban (reverse-engineer)
2. Hitung semantic similarity antara pertanyaan asli dan pertanyaan
   yang di-generate

**Implementasi**: [`evaluation/ragas_evaluation.py`](../evaluation/ragas_evaluation.py)
menggunakan Groq (default) atau OpenAI sebagai LLM judge.

> ⚠️ **Deviasi metodologi**: angka Faithfulness/Answer Relevance yang
> dilaporkan di [`hasil.md`](hasil.md) **tidak** dihasilkan dari
> `ragas_evaluation.py` di atas — script itu butuh API key Groq/OpenAI
> yang tidak tersedia saat evaluasi dijalankan. Sebagai gantinya, skor
> dihasilkan lewat **protokol LLM-as-a-judge manual/interaktif** (judge:
> Claude Sonnet 5, dinilai langsung di sesi chat terhadap
> `reference_answer`/`expected_titles` di `ground_truth.json`, pakai
> definisi Faithfulness/Answer Relevance yang sama seperti di atas).
> Ini paradigma yang sama (LLM-as-a-judge) tapi bukan implementasi RAGAS
> yang identik — judge model, algoritma skoring, dan jaminan
> reproducibility-nya berbeda. Lihat
> [catatan_riset.md § 9](catatan_riset.md#9-catatan-metodologi-phase-2-dijalankan-manual-claude-sebagai-judge-bukan-ragasdeepeval-otomatis-via-api)
> untuk daftar lengkap perbedaan dan limitasinya sebelum dikutip di
> laporan/skripsi.

#### Offline Proxy: Answer Contains

Selain RAGAS, Phase 1 juga menghitung **answer_contains** sebagai proxy
cepat — fraksi keyword expected yang ditemukan di jawaban:

```
answer_contains = |keywords found in answer| / |expected_answer_contains|
```

Ini bukan pengganti RAGAS, tetapi berguna untuk quick sanity check tanpa API key.

> ⚠️ **Sama seperti Precision@K, ini adalah lower-bound proxy, bukan
> presisi mutlak.** `expected_answer_contains` cuma daftar keyword sample,
> bukan kriteria exhaustive — jawaban yang benar secara substansi tapi
> kebetulan tidak memuat keyword persis dari sample tetap dihitung gagal.
> Jangan jadikan ini metrik tunggal buat klaim correctness; pakai
> berbarengan dengan Faithfulness/Answer Relevance dari RAGAS.

**Implementasi**: [`evaluation/metrics.py → answer_contains_check()`](../evaluation/metrics.py)

---

## Metrik 4: Operational — Latency

**Kategori**: Operational | **Fase**: Phase 1 (offline)

```
latency = time.time() (akhir) − time.time() (awal)
```

Wall-clock time dari input query hingga jawaban akhir ter-generate.
Mencakup seluruh ReAct loop (reasoner + tool_executor + responder).

Diukur dalam detik per query. Agregat: rata-rata per pipeline.

**Penting**: Latency sangat bergantung pada hardware (GPU, CPU), model
size, dan beban Ollama server. Bandingkan antar pipeline pada run yang
sama untuk fairness.

---

## Metrik 5: Operational — Token Cost / Usage

**Kategori**: Operational | **Fase**: Phase 1 (offline)

```python
token_usage = {
    "input_tokens":  state.token_usage.input_tokens,
    "output_tokens": state.token_usage.output_tokens,
    "total_tokens":  state.token_usage.total_tokens,
}
```

Diekstrak dari `usage_metadata` di setiap `AIMessage` yang dikembalikan
LLM selama workflow. `TokenUsage.add()` di
[`agent/core/state.py`](../agent/core/state.py) mengakumulasi token
dari semua panggilan LLM (reasoner + responder) dalam satu workflow run.

Agregat yang dilaporkan:
- **total_tokens**: Total token yang dikonsumsi seluruh pipeline run
- **avg_tokens_per_query**: Rata-rata token per query

Token cost penting untuk membandingkan efisiensi reasoning: agent yang
lebih cerdas seharusnya bisa menyelesaikan task dalam lebih sedikit
langkah ReAct → lebih sedikit token.

---

## Metrik 6: Operational — Tool Set Match

**Kategori**: Operational | **Fase**: Phase 1 (offline)

```
Tool Set Match = |called ∩ expected| / |expected| − destructive_penalty × destructive_count
```

Mengukur apakah agent memanggil tool-tool yang diharapkan, **tanpa
mempedulikan urutan** pemanggilan. Ini adalah adaptasi dari "Tool
Selection Accuracy" di factoid QA, disesuaikan untuk recommendation
system di mana:

- Agent boleh memanggil tool dalam urutan berbeda → order-independent
- Agent boleh memanggil tool tambahan yang **aman** (mis. laporan ekstra
  `categories_by_author`) → extra tools tidak dihukum
- Yang penting: **semua** expected tools dipanggil

**Contoh**:

```
expected_tools = ["books_by_vibe", "filter_by_branch"]

# Agent memanggil kedua tool + bonus categories_by_author → TSM = 1.0
called = {"categories_by_author", "books_by_vibe", "filter_by_branch"}
score = |{books_by_vibe, filter_by_branch} ∩ called| / 2 = 1.0

# Agent hanya memanggil satu dari dua → TSM = 0.5
called = {"books_by_vibe"}
score = |{books_by_vibe} ∩ called| / 2 = 0.5
```

**Implementasi**: [`evaluation/metrics.py → tool_set_match()`](../evaluation/metrics.py)

Tool names diekstrak dari `AgentState.tool_chain_log` menggunakan
[`extract_tools_used()`](../evaluation/metrics.py) yang mem-parse
entries seperti `"reasoner #1 → books_by_author({...})"`.

### Destructive Filter Penalty (gap fix)

Formula awal (`|called ∩ expected| / |expected|`) bersifat **recall-only** —
"extra tools tidak dihukum" by design, supaya agent boleh memanggil tool
tambahan yang aman tanpa rugi. Tapi ini membuat metrik buta terhadap kasus
nyata yang ditemukan di evaluasi LLM-as-Judge: reasoner (model 7–8B kecil)
kadang memanggil `filter_by_branch`/`_language`/`_collection_type` dengan
argumen yang **tidak disebut user sama sekali** (hallucinated), yang —
sebelum diperbaiki — menghapus seluruh pool kandidat ke 0 dan memaksa agent
menjawab "tidak ditemukan" walau buku yang relevan sebenarnya ada (lihat
analisis "contexts kosong" di [`hasil.md`](hasil.md)).

Dua perubahan terkait:

1. **`agent/nodes/tool_executor.py`**: filter yang akan menghapus pool
   non-kosong menjadi kosong kini **dibatalkan** (pool dipertahankan),
   ditandai `DESTRUCTIVE_FILTER_TAG` di observation/`tool_chain_log`.
2. **`evaluation/metrics.py → count_destructive_filter_calls()`**: parse
   `tool_chain_log` untuk tag tersebut, lalu `tool_set_match()` mengurangi
   skor `destructive_penalty` (default `0.25`) per kemunculan — capped ke
   `[0.0, 1.0]`.

Karena banyak query thematic/vibe tidak punya `expected_tools` (sehingga
`tool_set_match` selalu `-1.0`/tidak terevaluasi untuk query itu),
`destructive_filter_calls` juga dihitung **untuk setiap query** terlepas
dari `expected_tools` lewat `evaluate_single()` di
`run_comparative_evaluation.py`, dan diagregasi sebagai
`total_destructive_filter_calls` / `queries_with_destructive_filter` di
metadata output serta kolom `DF` pada ringkasan terminal.

---

## Menjalankan Evaluasi

### Phase 1: Offline Metrics (4 dari 6 metrik)

```bash
# Semua query di ground_truth.json, 3 pipeline default (standard, llama, qwen)
python evaluation/run_comparative_evaluation.py

# Hanya pipeline Llama, 5 query pertama
python evaluation/run_comparative_evaluation.py --pipelines llama --limit 5

# Mulai dari query ke-10
python evaluation/run_comparative_evaluation.py --start 10

# Kustom model
python evaluation/run_comparative_evaluation.py --llama-model llama3.1:8b --qwen-model qwen2.5:7b

# Arm ablasi (opt-in — TIDAK termasuk di "semua 3 pipeline" di atas;
# lihat tabel § Arm Ablasi di bawah)
python evaluation/run_comparative_evaluation.py --pipelines cot pure_react act_only planned

# Arm single-shot Planned (model via --planned-model, satu model per run)
python evaluation/run_comparative_evaluation.py --pipelines planned --planned-model llama3.1:8b

# Grid ablasi lengkap dalam satu run (3 pipeline default + 4 arm ablasi)
python evaluation/run_comparative_evaluation.py --pipelines standard cot llama qwen pure_react act_only planned

# A/B audit-off: matikan responder self-correct untuk SEMUA arm (file bertag _noaudit)
python evaluation/run_comparative_evaluation.py --pipelines llama qwen planned --no-self-correct
```

### Arm Ablasi (opt-in)

Selain 3 pipeline default, runner menyediakan **4 arm ablasi opt-in**. Standard
RAG + CoT-RAG + Act-only + Pure ReAct membentuk grid ala paper ReAct (Yao et
al.): *reason-only* vs *act-only* vs *keduanya* — tiap baris menambah tepat satu
kapabilitas. `planned` menambah sumbu lain: **loop vs tanpa-loop**.

| Arm | `--pipelines` | Reasoning | Acting (tool loop) | Gating | Implementasi |
|---|---|---|---|---|---|
| Standard RAG | `standard` | – | – | – | [`agent/core/standard_rag.py`](../agent/core/standard_rag.py) |
| CoT-RAG | `cot` | ✓ (satu rantai CoT sebelum jawab) | – | – | [`agent/core/standard_rag.py`](../agent/core/standard_rag.py) (`cot=True`) |
| Act-only | `act_only` | – | ✓ | – | [`agent/core/workflow_act_only.py`](../agent/core/workflow_act_only.py) |
| Pure ReAct | `pure_react` | ✓ (interleaved, field `thought`) | ✓ | – | [`agent/core/workflow_pure_react.py`](../agent/core/workflow_pure_react.py) |
| Vector-Gated ReAct (v2) | `llama` / `qwen` | ✓ (interleaved) | ✓ | ✓ *search-space* (seed presisi → prune → curate shrink-only) | [`agent/core/workflow.py`](../agent/core/workflow.py) |
| Planned (single-shot) | `planned` | ✓ (satu rencana di depan) | ✓ (eksekusi deterministik, tanpa loop) | ✓ *search-space* (1 plan → prune) | [`agent/core/workflow_planned.py`](../agent/core/workflow_planned.py) |

> **Vector-Gated = v2 (search-space-gated).** Versi awal (v1) menyempitkan
> *action space* via router+phase (route "vector" hanya boleh `filter_*`) — itu
> meruntuhkan retrieval multi-hop (P@3 3-hop ~0.10). Diganti v2 yang menyempitkan
> *search space* (pertumbuhan pool), bukan menu tool → multi-hop pulih (3-hop
> ~0.52). Data & rasional: [catatan_riset.md § 4.1](catatan_riset.md), hasil di
> [hasil.md](hasil.md) § Ringkasan Terbaru.

Perbandingan berpasangan yang dimaksudkan:

- **CoT-RAG vs Standard RAG**: retrieval keduanya identik (vector search
  top-5 yang sama) → Precision@K sama *by construction*; selisih metrik
  generation = kontribusi reasoning eksplisit tanpa acting.
- **Pure ReAct vs Act-only**: prompt identik kata-per-kata kecuali channel
  `thought` (harness, tool set, step budget, loop guard semuanya sama) →
  selisihnya = kontribusi interleaved CoT di dalam loop.
- **Vector-Gated (v2) vs Pure ReAct**: keduanya action space penuh; selisihnya
  = kontribusi *search-space gating* (seed presisi sekali → prune → curate
  shrink-only) vs pool tumbuh bebas.
- **Planned vs Vector-Gated / Pure ReAct**: prompt & tool sama, tapi Planned
  merencanakan seluruh urutan retrieval dalam SATU LLM call lalu eksekusi
  deterministik (tanpa loop reason⇄act) → selisihnya = apakah loop per-step
  memang diperlukan.

Catatan pembacaan hasil:

- **CoT-RAG memisahkan reasoning dari jawaban** lewat marker
  `JAWABAN AKHIR:` — hanya teks setelah marker yang masuk `final_answer`
  (yang dinilai `answer_contains`/RAGAS); rantai penalaran lengkap disimpan
  di `assembly_draft` + `reasoning_log`. Kalau marker tidak muncul (mis.
  output terpotong), jawaban fallback ke teks penuh dan ditandai
  `fallback_reason="cot_marker_missing"`.
- **Latency CoT-RAG lebih tinggi by design**: cap token output arm ini
  dinaikkan (`num_predict=1400` vs default 700) karena reasoning + jawaban
  tidak muat di cap default — biaya reasoning itu bagian dari trade-off
  yang diukur, bukan disembunyikan.
- **`tool_set_match` hanya bermakna untuk arm agentic.** Standard RAG dan
  CoT-RAG tidak pernah memanggil tool graph, jadi pada query yang punya
  `expected_tools` skornya 0.0 (bukan N/A) — jangan dibaca sebagai
  kegagalan; abaikan kolom TSM untuk kedua arm itu.
- **Semua arm agentic memakai `self_correct=False`** (audit deterministik
  responder tetap jalan, tapi tanpa LLM-retry) — A/B on/off menunjukkan
  self-correct *net-negatif* (AC turun, latency +15–35%, faithfulness ±0.02 tak
  konsisten). Cara toggle & hasil A/B: § *A/B: Responder Self-Correct* di bawah.

Menjalankan arm ablasi untuk **kedua model** (Llama & Qwen): flag model
per-arm (`--cot-model` / `--pure-react-model` / `--act-only-model`) hanya
menerima satu model per run, jadi jalankan dua kali — nama file output
sudah menyertakan slug model sehingga hasilnya tidak saling menimpa:

```bash
python evaluation/run_comparative_evaluation.py --pipelines cot pure_react act_only \
    --cot-model llama3.1:8b --pure-react-model llama3.1:8b --act-only-model llama3.1:8b
python evaluation/run_comparative_evaluation.py --pipelines cot pure_react act_only \
    --cot-model qwen2.5:7b --pure-react-model qwen2.5:7b --act-only-model qwen2.5:7b
```

### A/B: Responder Self-Correct (audit on/off)

Responder ([`agent/nodes/responder.py`](../agent/nodes/responder.py)) punya dua
lapisan grounding yang **terpisah** — penting dibedakan:

- **Audit deterministik** (5 dimensi, pure-Python regex: judul / penulis /
  branch / vibe / empty-answer — **tanpa LLM**) — ~gratis, selalu jalan, mengisi
  `state.violations` untuk observability. **Tidak** dimatikan.
- **Self-correct retry** — kalau audit menemukan violation, panggil LLM **sekali
  lagi** untuk menulis ulang jawaban. Ini LLM call kedua, dan **inilah** yang
  di-A/B-kan.

**Toggle**: flag `--no-self-correct` (atau env `DISABLE_SELF_CORRECT=1`) memaksa
`self_correct=False` untuk **semua** arm sekaligus tanpa mengedit tiap workflow;
file output ditandai suffix `_noaudit` supaya bisa dibandingkan ke run audit-ON:

```bash
# audit-OFF (VG-v2 + Planned) → bandingkan ke run yang sama tanpa flag
python evaluation/run_comparative_evaluation.py --pipelines llama qwen --no-self-correct
python evaluation/run_comparative_evaluation.py --pipelines planned --planned-model qwen2.5:7b --no-self-correct
```

**Temuan A/B** (VG-v2 & Planned × 2 model, delta OFF − ON): self-correct
**net-negatif** — P@3 tak berubah (audit memang tak menyentuh retrieval), **AC
justru naik** tanpa audit (+0.015…+0.060; retry sering memangkas keyword saat
menulis ulang buang "violation"), faithfulness geser ±0.02 tak konsisten, latency
turun **15–35%**. Karena itu `self_correct=False` kini **default** di semua arm
agentic (VG-v2, Planned, Act-only, Pure ReAct). Tabel delta lengkap & rasional:
[catatan_riset.md § 4.2](catatan_riset.md).

### Breakdown per Tipe Query

Untuk menganalisis bagaimana tiap arm berperilaku/beradaptasi terhadap
tipe input yang berbeda (1-hop vs multi-hop vs collaborative vs
branch-filter), agregat juga dihitung **per `query_type` dan per
`hop_count`**, di dua tempat:

1. **Metadata file hasil** — `run_comparative_evaluation.py` menulis
   `metadata.by_query_type` dan `metadata.by_hop_count` (n, P@3/P@5, AC,
   TSM, latency, destructive filter calls per kelompok) di setiap
   `eval_results_*.json`.
2. **Script analisis post-hoc** —
   [`evaluation/analyze_by_query_type.py`](../evaluation/analyze_by_query_type.py)
   membuat tabel pivot lintas-pipeline (baris = `query_type` terurut
   hop count, kolom = arm/model) dari result rows, jadi **bekerja juga
   untuk file hasil run lama** yang belum punya metadata di atas — tidak
   perlu mengulang evaluasi:

```bash
# Otomatis pakai file terbaru per (pipeline, model) di hasil_eval/
python evaluation/analyze_by_query_type.py --latest

# Atau sebut file eksplisit; simpan laporan markdown + CSV long-format
python evaluation/analyze_by_query_type.py --latest --out breakdown.md --csv breakdown.csv
```

Semantik metrik identik dengan agregat global (error rows dikecualikan
dari metrik kualitas; precision `-1`/TSM `None` = tidak terevaluasi, bukan
nol). Perhatikan jumlah query per tipe (`n`) saat menarik kesimpulan —
banyak `query_type` hanya punya 1–3 query, jadi perbedaan antar arm pada
satu tipe adalah indikasi pola perilaku, bukan signifikansi statistik;
gunakan rollup `hop_count` (n lebih besar per kelompok) untuk klaim yang
lebih kuat.

### Phase 2: RAGAS LLM-as-Judge (2 dari 6 metrik)

```bash
# Menggunakan Groq sebagai judge (gratis, recommended)
python evaluation/ragas_evaluation.py --use-groq

# Menggunakan OpenAI sebagai judge
python evaluation/ragas_evaluation.py
```

Phase 2 mengonsumsi file JSON dari Phase 1 (`eval_results_*.json`).

### Output

| File | Isi |
|------|-----|
| `evaluation/hasil_eval/eval_results_standard_<timestamp>.json` | Hasil Standard RAG (Phase 1) |
| `evaluation/hasil_eval/eval_results_agentic_llama_<timestamp>.json` | Hasil Agentic Llama (Phase 1) |
| `evaluation/hasil_eval/eval_results_agentic_qwen_<timestamp>.json` | Hasil Agentic Qwen (Phase 1) |
| `evaluation/hasil_eval/eval_results_cot_rag_<model>_<timestamp>.json` | Hasil CoT-RAG (Phase 1, ablasi opt-in) |
| `evaluation/hasil_eval/eval_results_pure_react_<model>_<timestamp>.json` | Hasil Pure ReAct (Phase 1, ablasi opt-in) |
| `evaluation/hasil_eval/eval_results_act_only_<model>_<timestamp>.json` | Hasil Act-only (Phase 1, ablasi opt-in) |
| `evaluation/hasil_eval/eval_results_planned_<model>_<timestamp>.json` | Hasil Planned single-shot (Phase 1, ablasi opt-in) |
| `evaluation/hasil_eval/ragas_comparison_*.csv` | Perbandingan RAGAS (Phase 2) |
| `evaluation/hasil_eval/ragas_comparison_*.md` | Laporan markdown (Phase 2) |

> `eval_results_agentic_{llama,qwen}_*` = Vector-Gated **v2** (search-space).
> Run dengan `--no-self-correct` menyisipkan suffix `_noaudit` sebelum `.json`
> (mis. `eval_results_planned_llama31_<ts>_noaudit.json`).

### Output Terminal (Phase 1)

Script mencetak progres per query (`P@5`, `AnswCont`, `TSM`, latency) lalu
tabel ringkasan per pipeline di akhir run. Contoh output dari run
aktual — termasuk seluruh angka Phase 1 & Phase 2 (LLM-as-Judge
Faithfulness/Answer Relevance per query) — ada di
**[`hasil.md`](hasil.md)**, dipisah dari dokumen ini supaya metodologi
tidak tercampur dengan laporan hasil yang berubah tiap kali evaluasi
dijalankan ulang.

---

## Shared Metrics Module

**File**: [`evaluation/metrics.py`](../evaluation/metrics.py)

Modul bersama yang berisi implementasi semua fungsi metrik:

| Fungsi | Metrik | Deskripsi |
|--------|--------|-----------|
| `precision_at_k()` | Retrieval | Proporsi top-K yang relevan |
| `answer_contains_check()` | Generation (proxy) | Fraksi keyword expected di jawaban |
| `tool_set_match()` | Operational | Set intersection tools called vs expected |
| `extract_tools_used()` | Helper | Parse tool names dari tool_chain_log |
| `build_contexts()` | Helper | Format BookNode → string untuk RAGAS |

Digunakan oleh `run_comparative_evaluation.py` (Phase 1) dan bisa
digunakan oleh script evaluasi lain.

---

## Connectivity Test

**File**: `test_connectivity.py`

Script pre-flight untuk memastikan semua service siap sebelum menjalankan workflow.

### Checks yang Dilakukan

| Check | Deskripsi |
|-------|-----------| 
| Neo4j Connection | Koneksi ke database berhasil |
| Neo4j Data (Books) | Ada node :Book di database |
| Neo4j Vector Index | Index `book_vector_index` ada |
| Ollama Service | Model tersedia (jika provider=ollama) |
| Groq API | API key valid (jika provider=groq) |
| Embedding Model | Model E5 bisa dimuat dan encode |
| LLM Invoke | LLM bisa merespon query sederhana |

### Cara Pakai

```bash
python test_connectivity.py
```

Output:
```
============================================================
  CONNECTIVITY TEST — Agentic GraphRAG
============================================================
  Provider: ollama
  Neo4j   : bolt://localhost:7687
------------------------------------------------------------
  ✅ Neo4j Connection: Connected
  ✅ Neo4j Data (Books): 10234 buku ditemukan
  ✅ Neo4j Vector Index: Index exists
  ✅ Ollama Service: Model 'llama3.1:8b' tersedia
  ⏭️ Groq API: Skipped (provider=ollama)
  ✅ Embedding Model: Loaded, dim=384
  ✅ LLM Invoke: Response: '2'
------------------------------------------------------------
  Semua 7 checks LULUS. Siap run: python test_agent.py
```

---

## Agent Test

**File**: `test_agent.py`

Script untuk testing end-to-end workflow dengan output debug lengkap.

```bash
# Default query
python test_agent.py

# Custom query
python test_agent.py "Buku romance berlatar pedesaan"
```

Output mencakup:
- Final answer
- Intent & entry point
- Jumlah enriched/curated buku
- Retry count & hallucination status
- Violations (jika ada)
- Curated context (top-5 buku)
- Tool chain log (langkah-langkah eksekusi)
- Reasoning log (alasan-alasan keputusan)
