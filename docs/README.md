# Agentic GraphRAG — Dokumentasi Komprehensif

## Daftar Isi

1. [Gambaran Umum](#gambaran-umum)
2. [Arsitektur Sistem](./arsitektur.md)
3. [Data Pipeline](./data_pipeline.md)
4. [Agent Workflow (Vector-Gated ReAct)](./agent_workflow.md)
5. [Graph Ontology](./graph_ontology.md)
6. [Evaluasi & Metrik](./evaluasi.md)
7. [Hasil Evaluasi](./hasil.md)
8. [Deployment & Konfigurasi](./deployment.md)
9. [API & Antarmuka](./antarmuka.md)
10. [Legacy: arsitektur 7-node](../legacy/README.md)
11. [Catatan Riset: Agentic vs Sequential](./catatan_riset.md)

---

## Gambaran Umum

**Agentic GraphRAG** adalah sistem rekomendasi buku berbasis Retrieval-Augmented
Generation yang mengikuti pola **hybrid GraphRAG**:

- **Knowledge Graph** (Neo4j) — multi-hop traversal atas ontologi buku
- **Vector Search** (E5 Embedding LazarusNLP, 384-dim) — semantic retrieval
- **Runtime Similarity** — tidak ada edge `SIMILAR_TO` pre-computed (sudah
  dihapus dari skema); kemiripan antar buku dihitung KNN murni saat runtime
  atas `book_vector_index`
- **Vector-Gated Agentic ReAct loop** — router rule-based memutuskan
  vector front-door vs seed lookup terstruktur sebelum loop dimulai, lalu
  agen otonom mengkurasi pool lewat tool apapun, urutan apapun, dan
  berhenti kapanpun (Router → Reasoner ⇄ ToolExecutor → Responder)
- **LLM Generation** (Ollama lokal / Groq Cloud — Llama 3.1)
- **Inline Multi-Dimensional Audit** — anti-halusinasi 5 dimensi dengan
  self-correct retry sekali

Sistem ini dibangun sebagai proyek skripsi untuk melayani rekomendasi buku dari
katalog Perpustakaan Umum DKI Jakarta (OPAC). Data diperoleh melalui scraping
HTML katalog, diproses melalui pipeline Bronze → Silver → Gold, lalu di-ingest
ke Neo4j dengan embedding vektor.

### Fitur Utama

| Fitur | Deskripsi |
|-------|-----------|
| Vector-Gated ReAct | Router rule-based (tanpa LLM) memilih vector front-door atau seed lookup graph sebelum loop; Reasoner ⇄ ToolExecutor → Responder mengkurasi pool yang sudah terbentuk. |
| Runtime Similarity | Tidak ada edge `SIMILAR_TO` pre-computed — kemiripan buku dihitung KNN murni saat runtime atas `book_vector_index`. |
| Multi-hop Graph Traversal | Hingga 3-hop intersection (vibe+setting+category) + collaborative "shared X" lookups, lewat 31 Cypher tool deterministik di `agent/tools/tools_catalog.py`. |
| Supernode-Aware Query Planning | Branch (~1.303 relasi/node) di-filter terakhir, bukan dipakai sebagai entry point. |
| Title-First Retrieval | `lookup_by_title` menerima judul sebagai input alami, bukan id. |
| Diverse Title Output | Vector search over-fetch + dedup-by-title (normalisasi edisi/punctuation). |
| Inline 5-Dimensional Audit | Hallucinated title, wrong author, wrong branch, wrong vibe, empty answer — dengan self-correct sekali. |
| Dual LLM Provider | Ollama (lokal) atau Groq (cloud) — switch via env var. |
| Standard RAG baseline | `agent/core/standard_rag.py` — single-hop vector search tanpa tool-calling, dipakai sebagai pembanding di evaluasi komparatif. |
| Legacy preserved | Arsitektur 7-node (`agent_v1`) dan ReAct pra-vector-gating (`agent_v2`) tetap runnable di `legacy/` untuk replay/ablasi/citation. |

### Tech Stack

| Komponen | Teknologi |
|----------|-----------|
| Knowledge Graph | Neo4j 5.25 Community + APOC |
| Vector DB | Neo4j Vector Index (cosine, 384 dims) |
| Embedding Model | LazarusNLP/all-indo-e5-small-v4 |
| LLM | Llama 3.1 (8B) via Ollama / Groq |
| Orchestration | Python 3.12 (sequential ReAct loop) |
| State Management | Pydantic v2 (immutable AgentState) |
| Data Pipeline | Pandas + MinIO (S3-compatible) |
| UI | React 18 + Vite + Tailwind (`frontend/`) — backend FastAPI (`app_web/`) |
| Container | Docker Compose |

### Struktur Direktori

```
agentic-graphrag/
├── agent/                       # Arsitektur produksi (Vector-Gated ReAct)
│   ├── core/
│   │   ├── state.py             # AgentState + BookNode + ReActStep + GraphQueryIntent (legacy)
│   │   ├── router.py            # classify_query(): vector vs graph front-door, rule-based
│   │   ├── workflow.py          # router → reasoner ⇄ tool_executor → responder
│   │   └── standard_rag.py      # Baseline non-agentic (vector search + generate) untuk evaluasi
│   ├── nodes/
│   │   ├── reasoner.py          # Otak ReAct: pilih action atau FINISH
│   │   ├── tool_executor.py     # Tangan: dispatch generic atas CYPHER_TOOLS, merge/narrow pool
│   │   └── responder.py         # Synthesis + 5-dim audit + 1× self-correct
│   ├── services/
│   │   ├── database.py          # Neo4j driver & query executor (lazy singleton)
│   │   └── llm_services.py      # LLM factory (Ollama/Groq, lazy)
│   └── tools/
│       ├── __init__.py          # Re-export dari tools_catalog.py
│       ├── tools_catalog.py     # CYPHER_TOOLS (31 tool) + SEED/MULTIHOP/CURATION slices
│       └── vector_tool.py       # E5 + Neo4j vector index (langsung, dedup-by-title)
│
├── legacy/                      # Arsitektur historis, masih runnable
│   ├── README.md
│   ├── agent_v1/                # Self-contained snapshot 7-node lama
│   │   ├── core/                # state.py, workflow.py
│   │   ├── nodes/               # router, tools_controller, reranker,
│   │   │                        # content_assembly, generation, policy_loop
│   │   ├── services/
│   │   └── tools/                # termasuk graph_tool.py (GraphSearchTool class)
│   └── agent_v2/                 # Snapshot 3-node ReAct pra-vector-gating
│       ├── core/, nodes/, services/, tools/   # termasuk graph_tool.py
│
├── frontend/                    # Antarmuka utama: React 18 + Vite + Tailwind
│   └── src/                     # App.tsx (chat), Admin.tsx (switch mode/model), api.ts
├── app_web/                     # Backend FastAPI (API-only) untuk React — mandiri
│   ├── server.py                # REST API (/api/query, /api/modes, /api/cache/*)
│   ├── agent_control.py         # Runtime switch 6 mode workflow + model LLM
│   ├── response_cache.py        # Cache respons penuh (namespace per mode+model)
│   ├── query_log.py             # Log kueri append-only (JSONL, analisis latency)
│   └── examples.py              # EXAMPLE_QUERIES (contoh kueri untuk /api/examples)
├── deprecated/                  # UI lama yang dipensiunkan — bukan bagian live app
│   ├── streamlit/               # Streamlit UI lama (streamlit_app, session_memory, query_cache)
│   └── vanilla_js/              # Vanilla JS UI lama (dulu di-host app_web di /)
├── data_pipeline/               # ETL pipeline (Bronze → Silver → Gold)
├── docker/
│   └── docker-compose.yml       # Neo4j 5.25
├── evaluation/
│   ├── run_comparative_evaluation.py   # Phase 1: 3-pipeline offline metrics
│   ├── ragas_evaluation.py             # Phase 2: LLM-as-judge (Faithfulness, Answer Relevance)
│   └── ground_truth.json               # 30 ground truth queries
├── shared/
│   └── schema/
│       ├── neo4j_schema.py
│       └── cypher_templates.py  # 24 Cypher template (single-hop, multi-hop, collaborative) — dipakai legacy/, tidak lagi oleh agent/tools/tools_catalog.py
├── test_connectivity.py
├── test_agent.py
└── .env
```
