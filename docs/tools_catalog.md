# Katalog Tool Retrieval (Parametric Cypher Tool Catalog)

> Sumber kode: [`agent/tools/tools_catalog.py`](../agent/tools/tools_catalog.py).
> Dokumen ini adalah referensi katalog tool retrieval yang dipakai seluruh arm
> agentic (Vector-Gated ReAct, Pure ReAct, Act-only, dan **Planned** — konfigurasi
> terbaik). Diperbarui setelah iterasi penyempurnaan tool (audit presisi retrieval).

## 1. Desain

Katalog bersifat **flat & deklaratif**: setiap tool adalah entri `nama → {params,
description, cypher}`. Tidak ada fungsi wrapper Python per-tool dan tidak ada query
building dinamis — hanya daftar parameter dan template Cypher statis yang memakai
binding `$param` native Neo4j. Eksekutor ([`agent/nodes/tool_executor.py`](../agent/nodes/tool_executor.py))
mengisi `params` dari argumen lalu menjalankan `cypher` lewat driver.

Keuntungan desain ini untuk skripsi: **action space eksplisit & dapat diaudit** —
setiap kemampuan retrieval satu baris Cypher yang bisa diverifikasi langsung ke graf,
tanpa logika tersembunyi.

## 2. Skema Graf (11 tipe node, 11 tipe relasi)

```
(:Author)-[:WROTE {role}]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                                 ↓
                            [:BELONGS_TO]->(:Category)
                            [:WRITTEN_IN]->(:Language)
                            [:AVAILABLE_AT]->(:Branch)        ← supernode
                            [:CLASSIFIED_AS]->(:DDCClass)
                            [:COLLECTION_TYPE]->(:CollectionType)
                            [:HAS_VIBE]->(:Vibe)              ← ekstraksi sinopsis
                            [:HAS_SETTING]->(:Setting)        ← ekstraksi sinopsis
                            [:FEATURES_CHARACTER]->(:Character) ← ekstraksi sinopsis
```

Field **reliable** berasal dari katalog perpustakaan (title, author, publisher, city,
category, DDC, language, collection type, branch). Field **rapuh** (Vibe, Setting,
Character, embedding) berasal dari **ekstraksi LLM atas sinopsis** — kualitas sinopsis
bervariasi dan tidak semua buku punya sinopsis. Ini melandasi mekanisme *fallback* di §6.

## 3. Inventaris Tool

Total **35 entri** di `CYPHER_TOOLS`. Kolom "exact" = memakai perbaikan
exact-match-first (§5). Kolom "slice" = keanggotaan registry (§7).

### 3.1 Single-hop — pencarian per satu atribut (SEED)

| Tool | Params | Exact-first |
|---|---|---|
| `books_by_category` | category | ✓ |
| `books_by_branch` | branch | ✓ |
| `books_by_author` | author | ✓ |
| `books_by_publisher` | publisher | ✓ |
| `books_by_vibe` | vibe | ✓ |
| `books_by_setting` | setting | ✓ |
| `books_by_character` | character | ✓ |
| `books_by_language` | language | ✓ |
| `books_by_collection_type` | collection_type | ✓ |
| `books_by_publisher_city` | city | ✓ |
| `books_by_ddc` | ddc_prefix | – (prefix `STARTS WITH`) |
| `lookup_by_title` | title, top_k | – |

### 3.2 Two-hop — irisan dua atribut (MULTIHOP)

| Tool | Params | Exact-first |
|---|---|---|
| `books_by_vibe_and_setting` | vibe, setting | ✓ |
| `books_by_vibe_and_category` | vibe, category | ✓ |
| `books_by_setting_and_category` | setting, category | ✓ |
| `books_by_author_and_vibe` | author, vibe | ✓ |
| `books_by_author_and_setting` | author, setting | ✓ |
| `books_by_author_and_category` | author, category | ✓ |
| `books_by_vibe_and_branch` | vibe, branch | ✓ |
| `books_by_category_and_branch` | category, branch | ✓ |
| `books_by_collection_type_and_category` | collection_type, category | ✓ |
| `books_by_ddc_and_branch` | ddc_prefix, branch | ✓ (branch saja) |

### 3.3 Three-hop — irisan tiga atribut (MULTIHOP)

| Tool | Params | Exact-first |
|---|---|---|
| `books_by_vibe_and_setting_and_category` | vibe, setting, category | ✓ |

### 3.4 Collaborative — "buku lain dengan X yang SAMA dengan judul Y" (COLLAB)

| Tool | Params | Keterangan |
|---|---|---|
| `books_sharing_vibe_with` | title | berbagi vibe dengan judul referensi |
| `books_sharing_vibe_with_setting` | title, setting | berbagi vibe + filter setting |
| `books_sharing_ddc_with` | title | klasifikasi DDC sama (exact-match, paling solid) |

### 3.5 Similarity — "buku MIRIP/SERUPA judul X" (SIMILARITY)

| Tool | Params | Keterangan |
|---|---|---|
| `search_similar_runtime` | title, raw_k, min_score, top_k | KNN embedding runtime; `raw_k`/`min_score`/`top_k` auto-default |

### 3.6 Kurasi pool & pelaporan (CURATION)

| Tool | Params | Semantik |
|---|---|---|
| `filter_by_branch` | book_ids, branch | narrow pool (irisan) |
| `filter_by_collection_type` | book_ids, collection_type | narrow pool |
| `filter_by_language` | book_ids, language | narrow pool |
| `categories_by_author` | author | non-book (teks laporan saja) |

### 3.7 Semantik & internal

| Tool | Params | Keterangan |
|---|---|---|
| `vector_search` | query | semantic search (E5 + Neo4j vector index); `cypher=None`, dieksekusi Python-side |
| `books_by_title_or_category_fuzzy` | keyword | **fallback** fuzzy judul/kategori (§6); bukan menu planner |
| `enrich_books` | book_ids | ambil relasi lengkap untuk sekumpulan id |
| `titles_to_ids` | titles | resolve judul → book_id |

## 4. Semantik Merge (di eksekutor)

- **FILTER_TOOLS** (`filter_by_branch/_collection_type/_language`): **menyempitkan**
  pool ke irisan; dijaga agar tidak menghapus seluruh pool (filter tak berdasar
  ditandai `DESTRUCTIVE_FILTER_TAG`, dihitung metrik).
- **NON_BOOK_TOOLS** (`categories_by_author`): tidak menyentuh pool, hanya teks observasi.
- **VECTOR_TOOLS** (`vector_search`): bypass `execute_query()`, memakai `VectorSearchTool`.
- **Lainnya** (seed/multihop/collaborative/similarity): **merge** ke pool — union relasi,
  ambil skor tertinggi + boost kecil per-tool.

## 5. Perbaikan presisi: EXACT-MATCH-FIRST

**Masalah.** Setiap `books_by_*` memfilter dengan
`toLower(node.name) CONTAINS toLower($param)` (substring) lalu memotong dengan
`LIMIT 15` **tanpa `ORDER BY`**. Jika nilai yang dicari adalah **substring** dari
node lain yang jauh lebih besar, hasil yang tepat tergeser. Contoh nyata (eval Q40):
setting `"desa"` (36 buku) juga tertangkap `"pedesaan"` (122 buku) via `CONTAINS`,
lalu `LIMIT 15` yang tak terurut mengembalikan 15 buku *pedesaan* acak — **menggeser
habis** semua buku "desa" yang tepat (P@3 → 0 walau ground truth benar).

**Solusi.** Tiap lookup menghitung skor `_exact` per buku (berapa node yang cocok
**persis** dengan nilai query) lalu `ORDER BY _exact DESC, b.book_id` **sebelum**
`LIMIT 15`:

```cypher
MATCH (b:Book)-[:HAS_SETTING]->(s:Setting)
WHERE toLower(s.name) CONTAINS toLower($setting)
WITH b, max(CASE WHEN toLower(s.name) = toLower($setting) THEN 1 ELSE 0 END) AS _exact
ORDER BY _exact DESC, b.book_id
LIMIT 15
...
```

Untuk tool multi-atribut, `_exact` = jumlah atribut yang cocok persis (0..N), sehingga
buku yang cocok pada **lebih banyak** atribut naik lebih dulu. Karena *exact ≥ substring*
selalu, perbaikan ini **tidak pernah meregresi** query yang sudah benar. DDC tetap
`STARTS WITH` (prefix memang disengaja); `vector_search` tak terpengaruh.

**Dampak.** Perubahan menyentuh **lapisan retrieval bersama** — berlaku untuk semua arm
(VG-v2, Pure ReAct, Planned). Verifikasi tool-level: Q40 P@3 **0 → 1.0**, tanpa meregresi
Q03/Q39/Q42 (tetap 1.0).

## 6. Mekanisme fallback: fuzzy judul/kategori

Atribut Vibe/Setting/Character adalah hasil ekstraksi sinopsis (§2) → retrieval
berbasis atribut ini bisa **kosong/sangat sedikit** untuk buku tanpa sinopsis layak.
`books_by_title_or_category_fuzzy(keyword)` mem-fuzzy-match keyword terhadap field
**reliable** — judul buku ATAU kategori mentah — sebagai jaring pengaman.

Pemicunya **otomatis & deterministik** di [`workflow_planned.py`](../agent/core/workflow_planned.py):
saat pool pasca-rencana **sparse** (`< 3`) DAN rencana menyentuh atribut rapuh
(vibe/setting/character) atau rencana kosong. Bukan tool yang bisa dipilih planner —
murni *fallback*.

## 7. Registry Slices & pemetaan workflow

| Slice | Isi | Dipakai oleh |
|---|---|---|
| `SEED_TOOLS` | 12 single-hop | VG-v2 (route graph), Planned, Pure ReAct |
| `MULTIHOP_TOOLS` | 11 kombinasi 2/3-atribut | idem |
| `COLLABORATIVE_TOOLS` | 3 "X sama dengan judul Y" | VG-v2 `EXPAND_TOOLS`, Planned |
| `SIMILARITY_TOOLS` | `search_similar_runtime` | **hanya `PURE_REACT_TOOLS`** — VG-v2 tak tersentuh |
| `CURATION_TOOLS` | 3 filter + `categories_by_author` | semua arm (fase curate) |
| `VECTOR_TOOLS` | `vector_search` | Pure ReAct / Planned (bukan menu VG) |
| `PURE_REACT_TOOLS` | gabungan semua di atas (**32 tool**) | Planned, Pure ReAct, Act-only |

`SIMILARITY_TOOLS` sengaja slice terpisah: `search_similar_runtime` hanya masuk
`PURE_REACT_TOOLS` (dipakai Planned), sehingga action space VG-v2 —
yang dibangun dari SEED+MULTIHOP+COLLABORATIVE — **tidak berubah**. Ini memperbaiki
tipe `runtime_similarity` tanpa mengubah arm lain.

`build_specs_prompt()` merender daftar tool ke reasoner/planner dengan **header
berkelompok** (SEMANTIC / SEED / MULTI-ATTRIBUTE / COLLABORATIVE / SIMILARITY / CURATION)
— mitigasi standar untuk menurunkan kesalahan pemilihan tool pada model kecil.

## 8. Riwayat perbaikan (iterasi pra-sidang)

1. **exact-match-first** (§5) — 21 tool `books_by_*`.
2. **ekspos `search_similar_runtime`** (§7) via `SIMILARITY_TOOLS`.
3. **fallback fuzzy** (§6) `books_by_title_or_category_fuzzy` + auto-trigger.

Lihat [`docs/analisis.md`](analisis.md) untuk analisis kegagalan per tipe kueri dan
[`docs/ground_truth.md`](ground_truth.md) untuk audit ground truth yang menegaskan
bahwa kegagalan retrieval bersumber dari **tool**, bukan ground truth.
