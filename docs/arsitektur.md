# Arsitektur Sistem

## Diagram Alur Tingkat Tinggi

```
┌───────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACE                                │
│      React SPA (frontend/)  →  FastAPI backend (app_web/server.py)      │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ run_workflow(query) — mode terpilih
                                 ▼
┌───────────────────────────────────────────────────────────────────────┐
│              AGENT WORKFLOW — Vector-Gated ReAct                       │
│                                                                         │
│   Router (rule-based) ─┬─ route="vector" → VectorSearchTool front-door│
│                         └─ route="graph"  → reasoner pilih 1 seed lookup│
│                                          │                              │
│     ┌──────────────┐  action   ┌────────────────┐                     │
│     │   Reasoner   │ ────────▶ │  Tool Executor │                     │
│     │   (brain)    │ ◀──────── │    (hands)     │  (maks 4 putaran)   │
│     └──────────────┘observation└────────────────┘                     │
│            │ FINISH                                                   │
│            ▼                                                          │
│     ┌──────────────┐                                                  │
│     │   Responder  │  synthesis + audit deterministik (1× self-correct)│
│     └──────────────┘                                                  │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                              ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│       NEO4J GRAPH DB        │   │        LLM SERVICE          │
│  • 12 node types            │   │  • Ollama (lokal, default)  │
│  • 31 Cypher tool deklaratif│   │  • Groq (cloud, opsional)   │
│  • Vector Index 384d cosine │   │  • llm        (plain-text)  │
│  • Tidak ada Text2Cypher    │   │  • llm_json   (JSON-mode)   │
└─────────────────────────────┘   └─────────────────────────────┘
```

Lihat [agent_workflow.md](agent_workflow.md) untuk detail tiap node dan
[graph_ontology.md](graph_ontology.md) untuk skema graf lengkap.

## Komponen Utama

### 1. User Interface Layer

Antarmuka aktif adalah **React SPA** yang berbicara ke **FastAPI backend** lewat
REST — backend-lah yang memanggil `agent.core.workflow.run_workflow(query)` (atau
salah satu dari 5 varian, sesuai mode yang dipilih di admin panel):

- **React SPA** ([frontend/](../frontend/)) — chat (`/`) + admin panel (`/admin`)
  untuk ganti mode workflow & model LLM saat runtime. Riwayat sesi di sisi klien
  (React state + `sessionStorage`, non-persisten lintas tab).
- **FastAPI backend** ([app_web/server.py](../app_web/server.py)) — expose
  `run_workflow` lewat REST (`POST /api/query`), plus response cache & query log.
  API-only dan mandiri (tidak lagi bergantung pada folder `app/` yang sudah dihapus).

UI lama sudah dipensiunkan ke `deprecated/` (Streamlit di `deprecated/streamlit/`,
vanilla JS di `deprecated/vanilla_js/`). Detail antarmuka aktif ada di
[antarmuka.md](antarmuka.md).

### 2. Agent Workflow Layer

Bukan pipeline bertahap kaku — **Vector-Gated ReAct**. Router rule-based
(tanpa LLM) memutuskan vector front-door atau satu seed lookup graph
*sebelum* loop dimulai; di dalam loop, Reasoner hanya memilih dari subset
tool yang relevan untuk `route`/`phase` saat itu (bukan benar-benar
"tool apapun") dan berhenti kapanpun (sampai `MAX_REACT_STEPS = 4`):

| Node | Tanggung Jawab | Input | Output |
|---|---|---|---|
| Router | Klasifikasi vector vs graph (regex, tanpa LLM) | `query` | `route` |
| Reasoner | Pilih tool berikutnya / putuskan FINISH | `scratchpad`, pool kandidat | `next_action` atau `curated_context` |
| Tool Executor | Eksekusi tool, merge/narrow pool | `next_action` | `enriched_data` (pool ter-update) |
| Responder | Sintesis jawaban + audit 5 dimensi (regex, bukan LLM) | `curated_context` | `final_answer`, `violations` |

Detail penuh (prompt, kasus tepi, format JSON, tool registry) ada di
[agent_workflow.md](agent_workflow.md).

**Pipeline alternatif**: `agent.core.standard_rag.run_standard_rag()` —
baseline single-hop vector search tanpa tool-calling, dapat dipilih via admin
panel (mode `standard`/`cot`) dan dipakai sebagai pembanding di evaluasi komparatif.

### 3. Data Layer

- **Neo4j Graph Database**: 12 jenis node, 11 jenis relasi (lihat
  [graph_ontology.md](graph_ontology.md)) — `Book`, `Author`, `Publisher`,
  `City`, `Category`, `Language`, `Branch`, `DDCClass`, `CollectionType`,
  `Vibe`, `Setting`, `Character`.
- **Neo4j Vector Index** (`book_vector_index`): 384 dimensi, cosine
  similarity, dipakai oleh `VectorSearchTool` (front-door semantik) dan
  oleh template `search_similar_runtime` (KNN dari satu buku referensi —
  pengganti edge `SIMILAR_TO` yang sudah dihapus dari skema; lihat catatan
  di [agent_workflow.md → Tool Registry](agent_workflow.md#tool-registry)
  soal tool ini belum diekspos ke reasoner saat ini).
- **Cypher Tool Catalog**: 31 tool deklaratif di
  [agent/tools/tools_catalog.py](../agent/tools/tools_catalog.py) — semua
  query graf deterministik, tidak ada Text2Cypher/LLM yang menyusun Cypher
  secara dinamis (bebas halusinasi struktur). Ini adalah katalog produksi
  saat ini; file lama [shared/schema/cypher_templates.py](../shared/schema/cypher_templates.py)
  (24 template, subset tanpa tool utility seperti `filter_by_*`) sekarang
  hanya dipakai oleh `legacy/agent_v1` dan `legacy/agent_v2`.

### 4. LLM Service Layer

**File**: [agent/services/llm_services.py](../agent/services/llm_services.py)

- **Ollama** (default, `ACTIVE_LLM_PROVIDER=ollama`): lokal, model diatur
  via `OLLAMA_MODEL` ( `llama3.1:8b`, `qwen2.5:7b`).
- **Groq** (`ACTIVE_LLM_PROVIDER=groq`): cloud LPU, untuk inferensi cepat.
- Dua varian diekspos sebagai lazy singleton: `llm` (plain-text, dipakai
  Responder & Standard RAG) dan `llm_json` (Ollama `format="json"` /
  Groq `response_format=json_object`, dipakai Reasoner — menghilangkan
  retry akibat output non-JSON dan membatasi `num_predict` untuk latency).

## State Management

Sistem menggunakan **Pydantic v2 BaseModel** (`AgentState`,
[agent/core/state.py](../agent/core/state.py)) sebagai state immutable.
Setiap node:
1. Menerima `AgentState` sebagai input
2. Memproses data
3. Mengembalikan state baru via `state.model_copy(update={...})`

Keuntungan pendekatan ini:
- **Type safety**: semua field tervalidasi Pydantic.
- **Immutability**: state tidak bisa dimutasi tidak sengaja di tengah loop.
- **Traceability**: setiap perubahan tercatat di `tool_chain_log` dan
  `reasoning_log` — bisa diputar ulang post-hoc untuk debugging.

## Self-Correction Mechanism (bukan retry seluruh workflow)

Arsitektur ini **tidak** mengulang seluruh workflow dari awal saat audit
gagal — beda dengan desain pipeline lama. Ada dua mekanisme koreksi yang
jauh lebih sempit, masing-masing lokal ke node-nya sendiri:

```
┌─ Di dalam Reasoner (selama ReAct loop) ───────────────────────┐
│ Tool call sama + args sama + hasil sebelumnya 0               │
│   → langsung paksa FINISH dengan pool apa adanya              │
│   (TIDAK ADA fallback ke vector_search — tool itu tidak ada   │
│    di action space reasoner sama sekali)                      │
└─────────────────────────────────────────────────────────────────┘

┌─ Di dalam Responder (setelah ReAct selesai) ──────────────────┐
│ Audit (5 dimensi, regex) menemukan violation                  │
│   → satu kali rewrite jawaban dengan instruksi eksplisit       │
│   → audit ulang; jika masih gagal → diterima paksa             │
│     (is_hallucinating=True, violations diisi untuk observability)│
└─────────────────────────────────────────────────────────────────┘
```

`AgentState.retry_count` dan `AgentState.reset_for_retry()` masih ada di
schema tapi **tidak dipanggil dari manapun** di kode aktif — keduanya
field vestigial yang dipertahankan untuk kompatibilitas dengan
UI/evaluator lama, bukan bagian dari control flow saat ini. Jangan
mengasumsikan ada loop balik ke "awal workflow" seperti versi sebelumnya.

## Supernode-Aware Design

`Branch` (cabang perpustakaan) punya rasio relasi jauh lebih tinggi
dibanding node lain — setiap buku punya tepat satu `AVAILABLE_AT` per
cabang tempat ia tersedia, tapi satu cabang besar (mis. Cikini) bisa
terhubung ke ribuan buku. Strategi penanganan di seluruh stack:

1. **Reasoner**: prinsip kerja #6 (lihat
   [agent_workflow.md](agent_workflow.md#node-1-reasoner-the-brain)) —
   kriteria lokasi/cabang selalu lewat `filter_by_branch` di langkah
   terpisah, dipanggil setelah pool kandidat terbentuk dari tool lain.
2. **Tool Executor**: `filter_by_branch` punya semantik khusus — bukan
   menambah buku baru ke pool, tapi **menyaring** pool ke irisan
   (intersection) yang cocok saja; buku yang tidak lolos filter dibuang
   dari pool, bukan dipertahankan dengan `branches=[]`. Dijaga juga agar
   filter yang ungrounded tidak menghapus pool non-kosong sampai 0 (lihat
   [Merge & Narrow Semantics](agent_workflow.md#merge--narrow-semantics)).
3. **Cypher tools**: query `books_by_branch` sendiri tetap dibatasi
   `LIMIT 15` di sisi MATCH utama untuk menghindari traversal yang terlalu
   lebar sebelum enrichment.

Urutan traversal yang ditanamkan ke Reasoner (seed/multihop dulu, supernode
terakhir):

```
route="vector": VectorSearchTool front-door (di luar loop)
route="graph":  books_by_{category,branch,author,publisher,vibe,setting,
                character,ddc,language,collection_type,publisher_city} /
                lookup_by_title  (seed, satu kali)
                  → books_by_{X}_and_{Y} (multihop, opsional)
                    → filter_by_branch / filter_by_collection_type /
                      filter_by_language  (curation, paling akhir)
```
