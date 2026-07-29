# Deployment & Konfigurasi

## Prerequisite

| Software | Versi | Keterangan |
|----------|-------|------------|
| Python | 3.10+ | Dengan venv |
| Docker & Docker Compose | Latest | Untuk Neo4j |
| Ollama | Latest | Jalan di **GPU remote** (lihat `OLLAMA_BASE_URL`), opsional jika pakai Groq |
| CUDA (opsional) | 11.8+ | Untuk GPU-accelerated embedding di mesin yang menjalankan kode Python |

---

## Quick Start

### 1. Clone & Setup Environment

```bash
git clone <repository-url>
cd agentic-graphrag

# Buat virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Konfigurasi Environment

Salin template `.env.example` ke `.env` lalu isi nilai sesuai environment Anda:

```bash
# Linux / Mac
cp .env.example .env

# Windows
copy .env.example .env
```

Field yang **wajib** diisi:

| Variable | Deskripsi |
|----------|-----------|
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | Credentials MinIO Anda |
| `NEO4J_AUTH` | Format `username/password` (sesuaikan dengan docker-compose) |
| `NEO4J_PASSWORD` | Password Neo4j (sama dengan di `NEO4J_AUTH`) |
| `OLLAMA_BASE_URL` | **Wajib kalau `ACTIVE_LLM_PROVIDER=ollama`** — alamat GPU remote tempat Ollama jalan (mis. `http://localhost:11450` lewat SSH tunnel). `agent/services/llm_services.py` sengaja **tidak punya fallback default** — kalau var ini kosong, proses gagal eksplisit (`ValueError`) alih-alih diam-diam jatuh ke Ollama lokal. |
| `GROQ_API_KEY` | Hanya jika `ACTIVE_LLM_PROVIDER=groq` |
| `GOOGLE_API_KEY` | Hanya jika pakai DeepEval LLM-as-judge |
| `HF_TOKEN` | Token HuggingFace untuk download embedding model |

Field yang sudah ada default aman (boleh dipakai langsung):

| Variable | Default |
|----------|---------|
| `MINIO_ENDPOINT` | `localhost:9000` |
| `NEO4J_URI` | `bolt://localhost:7687` |
| `ACTIVE_LLM_PROVIDER` | `ollama` |
| `OLLAMA_MODEL` | `llama3.1:8b` — sama untuk Llama maupun Qwen, ganti nilainya (atau pakai `--llama-model`/`--qwen-model` di `run_comparative_evaluation.py`) untuk switch model |
| `OLLAMA_KEEP_ALIVE` | `10m` — berapa lama Ollama menahan model di memori setelah request terakhir |
| `EMBEDDING_MODEL` | `LazarusNLP/all-indo-e5-small-v4` |
| `VECTOR_INDEX_NAME` | `book_vector_index` |
| `VECTOR_TOP_K` | `5` — jumlah kandidat unik final setelah dedup-by-title |
| `VECTOR_TOP_K_RAW` | `20` — jumlah kandidat mentah di-over-fetch sebelum dedup |
| `WEB_HOST` | `127.0.0.1` — host bind backend API (`app_web/server.py`); set `0.0.0.0` untuk akses LAN |
| `WEB_PORT` | `8001` — port HTTP backend API |
| `ADMIN_OLLAMA_MODELS` | `llama3.1:8b,qwen2.5:7b` — daftar model yang bisa dipilih di admin panel |
| `AGENTIC_GRAPHRAG_WEB_CACHE` | `.streamlit_sessions/web_response_cache.json` — response cache backend |
| `AGENTIC_GRAPHRAG_QUERY_LOG` | `.streamlit_sessions/web_query_log.jsonl` — log kueri append-only (JSONL) |
| `AGENTIC_GRAPHRAG_ADMIN_STATE` | `.streamlit_sessions/admin_state.json` — persist pilihan mode+model admin |

> ⚠️ **JANGAN commit file `.env`** ke git. File ini berisi kredensial dan sudah masuk `.gitignore`.

### 3. Jalankan Neo4j

```bash
cd docker
docker compose --env-file ../.env up -d
```

> ⚠️ `--env-file ../.env` **wajib** — `docker-compose.yml` membaca
> `NEO4J_AUTH` lewat interpolasi `${NEO4J_AUTH}` dari `.env` di project
> root. Tanpa flag ini, docker compose tidak menemukan `.env` (karena cwd-nya
> `docker/`, bukan root) dan diam-diam memakai string kosong untuk
> `NEO4J_AUTH` — Neo4j tetap bisa start tapi autentikasinya jadi tidak
> terduga. (Sengaja **tidak** dipakai `env_file:` di compose, karena itu
> akan menyuntikkan SEMUA variabel `.env` — termasuk `GROQ_API_KEY`,
> `HF_TOKEN`, kredensial MinIO — ke environment container Neo4j, yang tidak
> dibutuhkan sama sekali olehnya.)

Verifikasi: Buka http://localhost:7474 (Neo4j Browser)
- Username: sesuai `NEO4J_USERNAME` di `.env` (default `neo4j`)
- Password: sesuai `NEO4J_PASSWORD` di `.env`

### 4. Siapkan LLM

**Opsi A: Ollama (GPU remote)**
```bash
# Install & jalankan di SISI SERVER GPU remote, bukan di laptop developer
ollama pull llama3.1:8b
ollama pull qwen2.5:7b
ollama serve  # Jika belum auto-start

# Di sisi laptop/dev: pastikan OLLAMA_BASE_URL di .env mengarah ke server
# ini (SSH tunnel ke port lokal, atau alamat host langsung — lihat
# § Konfigurasi LLM di bawah). Tidak ada fallback ke Ollama lokal.
```

**Opsi B: Groq (Cloud)**
- Daftar di https://console.groq.com
- Dapatkan API key
- Set di `.env`: `ACTIVE_LLM_PROVIDER=groq` dan `GROQ_API_KEY=...`

### 5. Jalankan Data Pipeline (Jika Data Belum Ada)

```bash
# Bronze → Silver → Gold → Neo4j
python data_pipeline/bronze/bronze.py
python data_pipeline/silver/silver.py
python data_pipeline/gold/gold.py
python data_pipeline/utils/ingest_neo4j.py
```

### 6. Verifikasi Koneksi

```bash
python test_connectivity.py
```

Pastikan semua check ✅ sebelum lanjut.

### 7. Jalankan Aplikasi

```bash
# Test via CLI
python test_agent.py "Buku romance berlatar pedesaan"

# Backend API (FastAPI) — dari root repo
python -m app_web.server              # http://127.0.0.1:8001

# Frontend (React) — dari frontend/
cd frontend && npm install            # pertama kali saja
npm run dev                           # http://localhost:5173
```

Akses UI React di <http://localhost:5173>, backend API di <http://127.0.0.1:8001>
(lihat [antarmuka.md](antarmuka.md) untuk detail UI & REST API). Shortcut:
`start_app.bat` menjalankan backend + frontend sekaligus.

---

## Docker Compose

**File**: `docker/docker-compose.yml`

### Service: Neo4j

```yaml
services:
  neo4j:
    image: neo4j:5.25-community
    container_name: neo4j-agentic-graphrag
    ports:
      - "7474:7474"   # Neo4j Browser (HTTP)
      - "7687:7687"   # Bolt protocol
    environment:
      - NEO4J_AUTH=${NEO4J_AUTH}        # Format: username/password — dari .env (lihat catatan di bawah)
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_apoc_import_file_enabled=true
      - NEO4J_apoc_export_file_enabled=true
    volumes:
      - ./neo4j_data:/data
      - ./neo4j_logs:/logs
      - ./neo4j_conf:/conf
      - ../data_pipeline/gold:/var/lib/neo4j/import
    deploy:
      resources:
        limits:
          memory: 1.5g
```

> `NEO4J_AUTH` dibaca dari `.env` di project root lewat interpolasi
> `${NEO4J_AUTH}` — **wajib** jalankan compose dengan
> `docker compose --env-file ../.env ...` (lihat semua contoh perintah di
> bawah). Sengaja **tidak** dipakai `env_file:` di level service, karena
> itu akan menyuntikkan seluruh isi `.env` (termasuk `GROQ_API_KEY`,
> `HF_TOKEN`, kredensial MinIO) ke environment container Neo4j — tidak ada
> satupun dari itu yang dibutuhkan Neo4j.

### Perintah Docker

```bash
cd docker

# Start (--env-file wajib, lihat catatan di atas)
docker compose --env-file ../.env up -d

# Stop
docker compose down

# Lihat logs
docker compose logs -f neo4j

# Reset data (HATI-HATI: menghapus semua data)
docker compose down -v
rm -rf neo4j_data neo4j_logs
docker compose --env-file ../.env up -d
```

---

## Konfigurasi LLM

### Switch Provider

Cukup ubah `ACTIVE_LLM_PROVIDER` di `.env`:

```env
# Pakai Ollama (GPU remote — lihat OLLAMA_BASE_URL di bawah, BUKAN laptop lokal)
ACTIVE_LLM_PROVIDER=ollama

# Pakai Groq (cloud, lebih cepat, butuh internet)
ACTIVE_LLM_PROVIDER=groq
```

### Ganti Model Ollama

Llama dan Qwen sama-sama lewat provider `ollama`, dibedakan lewat
`OLLAMA_MODEL` saja:

```bash
# Pull model lain DI SISI SERVER GPU remote (bukan di laptop)
ollama pull llama3.2:3b      # Lebih kecil, lebih cepat
ollama pull qwen2.5:7b

# Update .env
OLLAMA_MODEL=llama3.2:3b
```

Untuk perbandingan Llama vs Qwen di evaluasi (`run_comparative_evaluation.py`),
nggak perlu edit `.env` bolak-balik — pakai flag `--llama-model`/`--qwen-model`,
keduanya jalan otomatis gantian (model sebelumnya di-unload dulu dari VRAM
sebelum yang baru dimuat — lihat [evaluasi.md](evaluasi.md)).

### Wajib: `OLLAMA_BASE_URL` ke GPU remote, bukan port lokal

Ollama proyek ini jalan di **GPU remote**, bukan di laptop developer.
`OLLAMA_BASE_URL` **wajib** diisi di `.env` — `agent/services/llm_services.py`
sengaja tidak punya fallback default; kalau var ini kosong, proses gagal
eksplisit (`ValueError`) di awal alih-alih diam-diam memakai Ollama lokal
kalau kebetulan ada yang jalan di laptop juga (silent wrong resource).

```env
# Contoh: GPU remote diakses lewat SSH tunnel ke port lokal 11450
OLLAMA_BASE_URL=http://localhost:11450
```

Kalau tidak pakai SSH tunnel, ganti dengan alamat host remote yang
sebenarnya (mis. `http://10.0.0.5:11434`).

---

## Konfigurasi Embedding

### Model Default

```env
EMBEDDING_MODEL=LazarusNLP/all-indo-e5-small-v4
```

Model ini dipilih karena:
- Optimized untuk Bahasa Indonesia
- Dimensi kecil (384) — efisien untuk storage dan computation
- Arsitektur E5 — mendukung prefix `query:` dan `passage:`

### Konvensi E5

- **Saat menyimpan** (gold layer): prefix `passage: ` + teks dokumen
- **Saat query** (vector_tool): prefix `query: ` + teks query pengguna

### Vector Index

```env
VECTOR_INDEX_NAME=book_vector_index
VECTOR_TOP_K=5
```

---

## Konfigurasi UI & Persistensi Backend

### Riwayat sesi (frontend)

Riwayat percakapan dikelola sepenuhnya di sisi klien oleh React (`sessionStorage`,
scope per-tab browser) — **tanpa konfigurasi server**. Riwayat bertahan saat
pindah route (`/` ↔ `/admin`) dan reload di tab yang sama, dan otomatis bersih
saat tab ditutup.

### Persistensi backend (FastAPI)

Backend menyimpan tiga file (semua default di `.streamlit_sessions/`, sudah masuk
`.gitignore`; nama folder legacy, boleh di-override):

```env
AGENTIC_GRAPHRAG_WEB_CACHE=.streamlit_sessions/web_response_cache.json   # response cache (per mode+model)
AGENTIC_GRAPHRAG_QUERY_LOG=.streamlit_sessions/web_query_log.jsonl       # log kueri append-only (JSONL)
AGENTIC_GRAPHRAG_ADMIN_STATE=.streamlit_sessions/admin_state.json        # pilihan mode+model admin
```

Catatan:

- Path bisa relatif (terhadap project root) atau absolute.
- Semua aman dihapus kapan saja — dibuat ulang otomatis (cache/log kosong, mode
  kembali ke default `agentic`).

> **Deprecated:** Streamlit lama (`deprecated/streamlit/`) memakai
> `AGENTIC_GRAPHRAG_SESSION_STORE` dan `AGENTIC_GRAPHRAG_QUERY_CACHE` — tidak lagi
> relevan untuk stack React + FastAPI.

---

## Troubleshooting

### Neo4j Tidak Bisa Connect

```
❌ Neo4j Connection: Connection refused
```

**Solusi**:
1. Pastikan Docker running: `docker ps`
2. Cek port: `docker compose logs neo4j`
3. Tunggu 30-60 detik setelah start (Neo4j butuh waktu booting)

### Ollama Model Tidak Ditemukan

```
❌ Ollama Service: Model 'llama3.1:8b' tidak ditemukan
```

**Solusi**:
```bash
ollama pull llama3.1:8b
ollama list  # Verifikasi
```

### Out of Memory (Embedding)

```
CUDA out of memory / MemoryError
```

**Solusi**:
- Kurangi batch size di `gold.py` (default 32)
- Jalankan di CPU: hapus CUDA atau set `CUDA_VISIBLE_DEVICES=""`
- Proses data per partisi (sudah diimplementasi di gold layer)

### Vector Index Belum Dibuat

```
❌ Neo4j Vector Index: Vector index 'book_vector_index' belum dibuat
```

**Solusi**:
```bash
python data_pipeline/utils/ingest_neo4j.py
```

Atau manual via Neo4j Browser:
```cypher
CREATE VECTOR INDEX book_vector_index IF NOT EXISTS
FOR (m:Book) ON (m.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 384,
  `vector.similarity_function`: 'cosine'
}}
```

### LLM Response Kosong

```
❌ LLM Invoke: LLM returned empty response
```

**Solusi**:
- Cek Ollama: `ollama run llama3.1:8b "test"`
- Cek Groq API key validity
- Cek koneksi internet (untuk Groq)
- Restart Ollama: `ollama serve`

---

## Production Considerations

> ⚠️ Proyek ini adalah **prototype skripsi**. Untuk production, pertimbangkan:

| Aspek | Saat Ini | Rekomendasi Production |
|-------|----------|----------------------|
| LLM | Ollama di single GPU remote / Groq free tier | GPU cluster / paid API |
| Database | Neo4j Community (single node) | Neo4j Enterprise (cluster) |
| Object Storage | MinIO lokal | AWS S3 / GCS |
| Embedding | CPU/single GPU | GPU cluster + batch inference |
| Monitoring | Log file | Prometheus + Grafana |
| Auth | Tidak ada | OAuth2 / API key |
| Caching | Tidak ada | Redis untuk query cache |
| Rate Limiting | Tidak ada | Per-user rate limit |
