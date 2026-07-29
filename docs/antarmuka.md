# API & Antarmuka

Antarmuka pengguna sistem ini adalah **React frontend** (`frontend/`) yang
berbicara ke **FastAPI backend** (`app_web/server.py`). Backend menjalankan
workflow agen yang sama (`agent.core.workflow.run_workflow` dan lima varian
lainnya) dan mengembalikan JSON. Programmatic API langsung ke workflow tetap
tersedia untuk script/evaluasi.

| Antarmuka | Stack | Entrypoint | Status |
|-----------|-------|------------|--------|
| **React Chat UI** | React 18 + Vite + Tailwind | `frontend/` (route `/`) | Antarmuka utama. |
| **React Admin Panel** | React 18 + Vite | `frontend/` (route `/admin`) | Ganti mode workflow & model LLM saat runtime. |
| FastAPI REST API | FastAPI (Python) | `app_web/server.py` | Backend (API-only) untuk React; `/` mengembalikan JSON deskripsi API. |
| Programmatic API | Python | `run_workflow(query)` | Integrasi script & evaluasi. |

> **UI lama sudah dipensiunkan** ke `deprecated/` dan **bukan lagi antarmuka yang
> didukung** (tidak mengikuti kontrak REST/observability terbaru):
>
> - Streamlit — `deprecated/streamlit/` (`streamlit_app.py`, `session_memory.py`, `query_cache.py`).
> - Vanilla JS — `deprecated/vanilla_js/` (dulu di-host backend di `/` & `/static`).
>
> Dokumen ini mendeskripsikan React frontend + FastAPI backend sebagai sumber
> kebenaran. `app_web/` kini mandiri (tidak lagi bergantung pada folder `app/`
> yang sudah dihapus).

---

## React Frontend

**Direktori**: `frontend/` · Detail developer: [`frontend/README.md`](../frontend/README.md)

Aplikasi SPA dua-route (`react-router`, lihat `frontend/src/main.tsx`):

| Route | Komponen | Fungsi |
|-------|----------|--------|
| `/` | `src/app/App.tsx` | Chat: ketik kueri → jawaban + carousel kartu buku. |
| `/admin` | `src/app/Admin.tsx` | Ganti mode workflow / model LLM, inspeksi & clear response cache. |

Jembatan ke backend ada di `src/api.ts` — client bertipe untuk `POST /api/query`
plus mapper yang mengubah `BookCard` backend menjadi `AgentBook` UI (fallback
cover, `synopsis`, meta `query_type`/`hop`/`elapsed`), dan wrapper endpoint admin.

### Menjalankan (development, dua terminal)

```bash
# Terminal 1 — backend (dari root repo)
python -m app_web.server        # API di http://127.0.0.1:8001

# Terminal 2 — frontend (dari frontend/)
npm install                     # pertama kali saja
npm run dev                     # http://localhost:5173
```

Vite mem-proxy `/api/*` ke backend (lihat `vite.config.ts`), sehingga browser
melakukan panggilan same-origin (tanpa setup CORS). Override target dengan
`VITE_API_TARGET` bila backend berjalan di host/port lain.

### Fitur UI

| Fitur | Deskripsi |
|-------|-----------|
| Book carousel | Hingga 12 kartu per jawaban; hover kartu untuk melihat sinopsis + ketersediaan cabang. Pill meta menampilkan `query_type` dan `{hop}-hop · {elapsed}s`. |
| Toolbar aksesibilitas | Mode kontras tinggi (`hc`) + penyesuaian ukuran font 5 tingkat, dari React state. Semua kontrol ≥44px dengan label ARIA. |
| Session history | Beberapa sesi chat disimpan **hanya di React state** untuk satu sesi browser — tidak ada persistensi, reload mengosongkan riwayat. |
| Offline demo | Bila `/api/query` gagal, jawaban contoh (keyed by regex) dirender agar UI tetap bisa didemokan tanpa backend. |
| Admin panel | Pilih 1 dari 6 mode workflow + model LLM, lalu terapkan; switch model meng-evict model lama dari VRAM GPU di sisi server. Cache/hasil di-namespace per `(mode, model)`. |

### Konfigurasi (build/dev)

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `VITE_API_TARGET` | `http://127.0.0.1:8001` | Backend tujuan proxy `/api` saat dev. |
| `VITE_API_BASE` | `""` (same-origin) | Base API absolut untuk backend produksi/remote (dipakai saat build). |

### Production build

```bash
npm run build      # emit bundle statis ke frontend/dist/
npx vite preview   # opsional: serve dist/ lokal untuk cek cepat
```

`dist/` adalah bundle statis; layani di web server apa pun atau lewat FastAPI.
Karena `/admin` adalah route sisi-klien, host harus fallback ke `index.html`
untuk path yang tidak dikenal (SPA rewrite).

---

## FastAPI Backend & REST API

**File**: `app_web/server.py`

Backend menjalankan workflow yang **sedang dipilih** (via `app_web/agent_control.py`),
menyimpan respons lengkap di `ResponseCache`, dan mencatat tiap kueri ke
`QueryLog` (append-only, untuk analisis latency/usage). Semua endpoint terbuka
untuk CORS (`allow_origins=["*"]`).

### Menjalankan

```bash
# Direkomendasikan
python -m app_web.server

# Atau via uvicorn langsung (auto-reload saat dev)
uvicorn app_web.server:app --reload --host 0.0.0.0 --port 8001
```

Backend ini **API-only**: root `/` mengembalikan JSON deskripsi API (UI-nya
adalah React app di `frontend/`, dev di <http://localhost:5173>). Konfigurasi:

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `WEB_HOST` | `127.0.0.1` | Host bind FastAPI (set `0.0.0.0` untuk akses LAN). |
| `WEB_PORT` | `8001` | Port HTTP. |
| `ADMIN_OLLAMA_MODELS` | `llama3.1:8b,qwen2.5:7b` | Daftar model yang bisa dipilih di admin panel. |
| `AGENTIC_GRAPHRAG_ADMIN_STATE` | `.streamlit_sessions/admin_state.json` | Path persist pilihan (mode, model) admin. |

### Ringkasan Endpoint

| Method & Path | Fungsi |
|---------------|--------|
| `GET /` | JSON deskripsi API + daftar endpoint (UI adalah React app di `frontend/`). |
| `GET /api/health` | `{status, provider, model, mode}`. |
| `GET /api/examples` | Daftar contoh kueri (`app_web.examples.EXAMPLE_QUERIES`). |
| `POST /api/query` | Jalankan workflow terpilih → `QueryResponse`. |
| `GET /api/modes` | Snapshot mode & model yang tersedia + pilihan aktif. |
| `POST /api/mode` | Ganti mode dan/atau model (switch model evict VRAM). |
| `GET /api/cache/stats` | Counter hits/misses + jumlah entri cache. |
| `POST /api/cache/clear` | Kosongkan seluruh response cache. |

#### `POST /api/query`

Request:

```json
{ "query": "Rekomendasikan buku romance berlatar pedesaan", "use_cache": true }
```

Response (`QueryResponse`):

```json
{
  "answer": "Berikut beberapa rekomendasi…",
  "books": [
    {
      "book_id": "116151",
      "title": "Judul Buku",
      "authors": ["Nama Penulis"],
      "categories": ["Fiksi"],
      "vibes": ["romance"],
      "settings": ["pedesaan"],
      "available_at": ["Cikini", "Matraman"],
      "is_available": true,
      "relevance_score": 0.892,
      "cover_url": "https://…",
      "pub_year": 2018,
      "synopsis": "Ringkasan singkat buku…"
    }
  ],
  "elapsed": 12.34,
  "from_cache": false,
  "intent": "react",
  "query_type": "vector",
  "hop": 1,
  "traversal": [],
  "tool_chain": ["router → vector front-door (25 kandidat)", "…"],
  "reasoning": ["#2 Pool relevan & tersedia, finalisasi.", "…"],
  "violations": [],
  "error": null
}
```

Catatan perilaku:

- **Cache**: `use_cache=true` mengecek `ResponseCache` yang menyimpan **respons
  lengkap** (answer + books + meta), di-namespace per `(mode, model)`. Hit
  mengembalikan respons utuh dengan `from_cache=true`. Server hanya menulis cache
  untuk hasil sukses yang **tidak kosong** (parse-fail transien yang menghasilkan
  0 buku tidak dikunci di cache).
- **`query_type`** = keputusan front-door router (`"vector"`/`"graph"`), fallback
  ke `intent` yang di-assign Reasoner. **`hop`** = jumlah langkah traversal graf
  (jawaban vector-only selalu 1-hop).
- **`synopsis`** diambil dari `book.abstract_clean` (bisa `null`).
- **`cover_url`** yang kosong/sentinel base-path di-rewrite ke placeholder cover.
- `intent`, `traversal` bersifat legacy: `intent` selalu `"react"` untuk pipeline
  agentic, dan `traversal` selalu `[]` karena `state.graph_intent` tidak pernah
  diisi `run_workflow()` saat ini (lihat
  [agent_workflow.md → State Schema](agent_workflow.md#state-schema)). Pakai
  `query_type`/`tool_chain`/`reasoning` untuk observability.
- `400` bila `query` kosong; `500` `detail: "workflow error: <pesan>"` bila
  workflow melempar exception (di-log via `logger.exception`).

#### Admin: `GET /api/modes` · `POST /api/mode`

`GET /api/modes` mengembalikan snapshot:

```json
{
  "current_mode": "agentic",
  "current_model": "llama3.1:8b",
  "provider": "ollama",
  "modes": [ { "key": "agentic", "label": "Agentic ReAct", "description": "…" }, … ],
  "models": ["llama3.1:8b", "qwen2.5:7b"]
}
```

`POST /api/mode` menerima `{ "mode": "planned", "model": "qwen2.5:7b" }` (salah
satu boleh `null`) dan menerapkannya atomik. Enam mode workflow tersedia:

| `key` | Label | Entrypoint |
|-------|-------|------------|
| `agentic` | Agentic ReAct (default) | `agent.core.workflow.run_workflow` |
| `pure_react` | Pure ReAct | `agent.core.workflow_pure_react.run_workflow_pure_react` |
| `act_only` | Act-only ReAct | `agent.core.workflow_act_only.run_workflow_act_only` |
| `planned` | Planned (plan-then-execute) | `agent.core.workflow_planned.run_workflow_planned` |
| `standard` | Standard RAG (baseline) | `agent.core.standard_rag.run_standard_rag` |
| `cot` | CoT RAG | `agent.core.standard_rag.run_standard_rag_cot` |

Switch model meng-evict model lama dari VRAM (`keep_alive:0`), me-reset singleton
`llm_services`, dan me-reload modul yang meng-bind LLM saat import
(`reasoner`, `responder`, `workflow_planned`) — mengatasi bug "Qwen diam-diam
menjalankan Llama" (lihat [catatan_riset.md](catatan_riset.md)). Sebuah lock
menserialkan switch dan query agar swap tidak terjadi di tengah kueri.

### Skema Pydantic

```python
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    use_cache: bool = Field(default=True)

class BookCard(BaseModel):
    book_id: str
    title: str
    authors: list[str]
    categories: list[str]
    vibes: list[str]
    settings: list[str]
    available_at: list[str]
    is_available: bool
    relevance_score: float
    cover_url: str
    pub_year: int | None = None
    synopsis: str | None = None

class QueryResponse(BaseModel):
    answer: str
    books: list[BookCard]
    elapsed: float
    from_cache: bool
    intent: str | None = None
    query_type: str | None = None
    hop: int = 1
    traversal: list[str] = []
    tool_chain: list[str] = []
    reasoning: list[str] = []
    violations: list[str] = []
    error: str | None = None
```

### Contoh Pemakaian via `curl`

```bash
# Contoh kueri
curl -s http://localhost:8001/api/examples | jq .

# Submit query (tanpa cache)
curl -s http://localhost:8001/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Buku romance berlatar pedesaan", "use_cache": false}' \
  | jq '{answer, query_type, hop, n_books: (.books | length), elapsed}'

# Health & mode aktif
curl -s http://localhost:8001/api/health | jq .

# Ganti mode/model
curl -s http://localhost:8001/api/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "planned", "model": "qwen2.5:7b"}' | jq '{current_mode, current_model}'
```

### Memori Sesi

Backend **stateless** — tiap `POST /api/query` adalah turn independen ke agen
(`run_workflow` menerima satu query string dan tidak mempertahankan konteks
lintas pesan). Riwayat multi-sesi sepenuhnya urusan frontend (React state,
non-persisten). Bila perlu persistensi, frontend dapat memakai
`localStorage`/`sessionStorage` atau backend menambah endpoint sesi custom.

---

## Programmatic API

### Basic Usage

```python
from agent.core.workflow import run_workflow

state = run_workflow("Rekomendasikan buku romance berlatar pedesaan")

print(state.final_answer)        # Teks rekomendasi final
print(state.route)               # "vector" | "graph" — keputusan router sebelum loop
print(state.phase)               # "seed" | "curate" saat workflow berakhir
print(state.curated_context)     # List[BookNode] (top-8 buku)
print(state.retry_count)         # Selalu 0 — tidak ada retry ReAct, hanya self-correct 1x di Responder
print(state.is_hallucinating)    # False jika lolos audit
print(state.violations)          # List[PolicyViolation] (kosong jika lolos)
print(state.error)               # None jika sukses
```

Enam entrypoint (`run_workflow`, `run_workflow_pure_react`, `run_workflow_act_only`,
`run_workflow_planned`, `run_standard_rag`, `run_standard_rag_cot`) semuanya
menerima query string dan mengembalikan `AgentState`, sehingga interchangeable
(inilah yang di-switch admin panel via `agent_control.get_runner()`).

### Akses Detail Buku

```python
for book in state.curated_context:
    print(f"Judul: {book.title}")
    print(f"Penulis: {book.author_names}")
    print(f"Vibe: {book.vibe_names}")
    print(f"Setting: {book.setting_names}")
    print(f"Tersedia: {book.is_available}")
    print(f"Lokasi: {book.available_at}")
    print(f"Skor: {book.relevance_score:.3f}")
```

### Akses Observability

```python
print(f"Route: {state.route}")   # "vector" | "graph"
print(f"Phase: {state.phase}")   # "seed" | "curate"

for log in state.tool_chain_log:     # langkah yang dieksekusi (router, reasoner, tool_executor)
    print(f"  -> {log}")

for reason in state.reasoning_log:   # thought reasoner per step
    print(f"  - {reason}")
```

> `state.graph_intent` masih ada di schema (lihat
> [agent_workflow.md → State Schema](agent_workflow.md#state-schema)) tapi tidak
> pernah diisi oleh `run_workflow()` saat ini — selalu `None`. Pakai
> `tool_chain_log`/`reasoning_log` sebagai sumber observability yang aktif.

---

## AgentState Schema

Skema lengkap (termasuk `route`/`phase`, `scratchpad`/`ReActStep`, dan field
legacy seperti `graph_intent`) didokumentasikan di
[agent_workflow.md → State Schema](agent_workflow.md#state-schema) — bagian ini
hanya quick-reference field yang relevan untuk consumer API/UI:

| Field | Type | Deskripsi |
|-------|------|-----------|
| `query` | str | Query input pengguna |
| `route` | str \| None | `"vector"` \| `"graph"` — keputusan router sebelum loop ReAct |
| `phase` | str | `"seed"` \| `"curate"` — tahap loop saat workflow berakhir |
| `enriched_data` | List[BookNode] | Pool kandidat penuh (vector front-door + hasil tool) |
| `curated_context` | List[BookNode] | Top-8 buku terkurasi reasoner saat FINISH |
| `final_answer` | str | Jawaban final untuk user |
| `is_hallucinating` | bool | Hasil audit Responder |
| `violations` | List[PolicyViolation] | Pelanggaran yang ditemukan (5 dimensi) |
| `reasoning_log` | List[str] | Log thought reasoner (append-only) |
| `tool_chain_log` | List[str] | Log eksekusi tool (append-only) |
| `error` | str \| None | Pesan error (None jika sukses) |

> `intent`, `entry_point`, dan `graph_intent` masih ada di schema untuk
> kompatibilitas mundur, tapi **tidak pernah diisi secara dinamis** oleh
> `run_workflow()` saat ini — `intent` selalu `"react"`, `entry_point` selalu
> `"agent"`, `graph_intent` selalu `None`.

---

## Database Service

### Execute Query

```python
from agent.services.database import execute_query

# Simple query
results = execute_query("MATCH (b:Book) RETURN b.title LIMIT 5")

# Parameterized query
results = execute_query(
    "MATCH (b:Book) WHERE b.book_id IN $ids RETURN properties(b) AS book",
    {"ids": ["123456", "789012"]}
)
```

### Get Driver (untuk advanced usage)

```python
from agent.services.database import get_driver

driver = get_driver()
with driver.session() as session:
    result = session.run("MATCH (n) RETURN count(n)")
    ...
```

---

## LLM Service

### Get LLM Instance

```python
from agent.services.llm_services import get_llm

# Auto-detect dari ACTIVE_LLM_PROVIDER
llm = get_llm()

# Force specific provider
llm_ollama = get_llm("ollama")
llm_groq = get_llm("groq")
```

### Direct Usage

```python
from agent.services.llm_services import llm
from langchain_core.messages import HumanMessage, SystemMessage

response = llm.invoke([
    SystemMessage(content="Kamu asisten perpustakaan."),
    HumanMessage(content="Rekomendasikan buku romance."),
])
print(response.content)
```

---

## Tools

### Vector Search Tool

```python
from agent.tools.vector_tool import VectorSearchTool

tool = VectorSearchTool()
results = tool.search("buku romance pedesaan", top_k=5)  # Returns List[BookNode]

for book in results:
    print(f"{book.title} (score: {book.relevance_score:.3f})")
```

`driver` adalah parameter constructor opsional yang dipertahankan untuk
kompatibilitas tapi tidak dipakai langsung — `VectorSearchTool` query lewat
`agent.services.database.execute_query()` di internal.

### Cypher Tool Catalog (graph lookups)

Tidak ada lagi class `GraphSearchTool` (`agent/tools/graph_tool.py` sudah
dihapus). Lookup terstruktur sekarang berupa katalog deklaratif `CYPHER_TOOLS` —
tiap entri adalah `{params, description, cypher}`, tanpa wrapper Python per-tool.
Untuk dipanggil langsung (di luar ReAct loop), jalankan `cypher`-nya sendiri lewat
`execute_query()`:

```python
from agent.tools import CYPHER_TOOLS
from agent.services.database import execute_query

spec = CYPHER_TOOLS["books_by_vibe_and_setting"]
results = execute_query(spec["cypher"], {"vibe": "romance", "setting": "pedesaan"})

# Filter pool ke satu branch (book_ids wajib diisi manual di luar loop ReAct)
spec = CYPHER_TOOLS["filter_by_branch"]
results = execute_query(spec["cypher"], {"book_ids": ["123", "456"], "branch": "Cikini"})
```

Daftar lengkap 31 tool dan tool mana yang benar-benar terjangkau reasoner
(`SEED_TOOLS`/`MULTIHOP_TOOLS`/`CURATION_TOOLS`) ada di
[agent_workflow.md → Tool Registry](agent_workflow.md#tool-registry).
