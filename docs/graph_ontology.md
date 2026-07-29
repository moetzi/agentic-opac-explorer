# Graph Ontology

## Schema Graf

**File sumber kebenaran**: [shared/schema/neo4j_schema.py](../shared/schema/neo4j_schema.py)
(dipakai pipeline & agent) dan [shared/schema/cypher_templates.py](../shared/schema/cypher_templates.py)
(24 template Cypher statis).

Knowledge graph didesain dengan prinsip **supernode-aware** — node dengan
relasi tinggi (Branch) selalu diakses terakhir untuk menghindari traversal
yang terlalu lebar.

### Diagram Ontologi (12 node types, 11 relationship types)

```
(:Author)-[:WROTE {role}]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                                ↓
                           [:BELONGS_TO]->(:Category)
                           [:WRITTEN_IN]->(:Language)
                           [:AVAILABLE_AT]->(:Branch)        ⚠️ SUPERNODE
                           [:CLASSIFIED_AS]->(:DDCClass)
                           [:COLLECTION_TYPE]->(:CollectionType)
                           [:HAS_VIBE]->(:Vibe)              ← LLM-extracted
                           [:HAS_SETTING]->(:Setting)        ← LLM-extracted
                           [:FEATURES_CHARACTER]->(:Character) ← LLM-extracted
```

> **Tidak ada relasi `SIMILAR_TO` di schema ini.** Versi lama membangun edge
> `Book-[:SIMILAR_TO]->Book` pre-computed saat ingestion (KNN, threshold
> ≥0.85). Edge itu **dihapus total** — bukan dinonaktifkan, tapi dihapus
> dari schema, cypher templates, `GraphSearchTool`, dan `BookNode`
> (field `similar_to` sudah tidak ada). Kemiripan antar buku sekarang
> dihitung 100% runtime lewat `book_vector_index` (lihat § Cypher Templates
> dan [agent_workflow.md](agent_workflow.md)). Alasannya: edge pre-computed
> jadi stale begitu data baru ditambahkan tanpa re-ingestion penuh, dan
> runtime KNN dengan vector index modern cukup cepat untuk tidak perlu
> di-precompute.

### Klasifikasi Node

| Kelompok | Node | Sumber Data |
|---|---|---|
| Entitas inti | `Book` | OPAC bibliografis |
| Bibliografis | `Author`, `Publisher`, `Category`, `Language`, `City` | OPAC bibliografis (field metadata) |
| Kepustakaan | `Branch`, `DDCClass`, `CollectionType` | OPAC holdings (`call_number`, `branch_name`, `jenis_bahan`) |
| Derivatif (LLM) | `Vibe`, `Setting`, `Character` | Diekstrak Ollama dari `abstract_clean` ([silver1.py](../data_pipeline/silver/silver1.py)) — **open-vocabulary**, bukan enum tetap |

> Beda penting dengan versi lama: dulu Vibe (10 nilai) dan Setting (8 nilai)
> adalah enum tetap dari pattern regex. Sekarang LLM menentukan label sendiri
> dari konteks sinopsis tiap buku — jumlah dan isi node `Vibe`/`Setting`
> bertambah organik sesuai keberagaman data, tidak dibatasi daftar tetap.

---

## Node Types Detail

### Book (Node Inti)

```
(:Book {
  book_id: STRING (UNIQUE),
  title: STRING,
  isbn_13: STRING | NULL,
  pub_year: INTEGER | NULL,
  total_pages: INTEGER | NULL,
  is_fiction: BOOLEAN,
  abstract_clean: STRING | NULL,
  ddc_class: STRING | NULL,        -- kode DDC 3 digit, mis. "813"
  edisi: STRING | NULL,
  language: STRING | NULL,
  cover_url: STRING | NULL,
  embedding: LIST<FLOAT>[384]      -- E5 (LazarusNLP/all-indo-e5-small-v4)
})
```

### Author

```
(:Author { name: STRING (UNIQUE) })
-- Relasi WROTE membawa property:
[:WROTE {role: STRING}]   -- "penulis" | "penerjemah" | "ilustrator" | "editor" | dll.
```

### Publisher & City

```
(:Publisher { name: STRING (UNIQUE) })
(:City       { name: STRING (UNIQUE) })
-- (:Publisher)-[:LOCATED_IN]->(:City) dibuat via FOREACH conditional
-- saat ingest (hanya jika city tidak NULL)
```

### Category

```
(:Category { name: STRING (UNIQUE) })
```

### Language

```
(:Language { name: STRING (UNIQUE) })
-- Contoh nilai dari data: "Indonesia", "Inggris", "Jepang", "Arab"
```

### Branch (SUPERNODE ⚠️)

```
(:Branch { name: STRING (UNIQUE), address: STRING | NULL })
-- Contoh: "Perpustakaan Jakarta - Cikini", "Perpustakaan Jakarta Barat - Tanjung Duren"
-- ⚠️ Rata-rata relasi per node jauh di atas node lain → SELALU filter terakhir
--   di tool-calling agent (lihat agent_workflow.md § filter_by_branch)
```

> `address` diisi dari `holdings[].branch_address` di bronze, dibawa lewat
> `silver.py` (`branches_metadata`) → `gold.py` (`rels_available.json` +
> `nodes_branch.json`) → `ingest_neo4j.py` (`SET br.address = value.address`
> di task `rels_available`). Sebelumnya field ini dideklarasikan di
> `neo4j_schema.py` tapi tidak pernah diisi — sudah diperbaiki.
>
> Catatan batas perbaikan: address sekarang benar tersimpan di node Neo4j,
> tapi **belum disurfacekan balik ke agent** — semua 24 Cypher template
> yang mengembalikan `branches` masih hanya `collect(DISTINCT {name: br.name})`
> (tanpa address), dan `BranchNode` di `agent/core/state.py` masih
> `{name: str}` saja. Menambahkan address ke jalur agent berarti mengedit
> proyeksi `branches` di setiap template — sengaja belum dilakukan di sini
> karena scope-nya beda (surfacing ke UI/jawaban, bukan lagi "field
> dideklarasikan tapi tidak diisi").

### DDCClass

```
(:DDCClass { code: STRING (UNIQUE), description: STRING })
```

`code` = 3 digit Dewey Decimal Classification dari `holdings[].call_number`
(mis. `"813 SUY p"` → `code="813"`). `description` dipetakan dari digit
pertama (`ddc_division`) lewat label tetap (10 kelas, fixed by design — ini
bagian dari standar DDC, bukan hasil ekstraksi):

> ⚠️ **`description` dideklarasikan di skema tapi tidak ter-ingest ke
> Neo4j saat ini.** `gold.py` menulisnya dengan benar ke
> `graph/nodes_ddc.json`, tapi `ingest_neo4j.py` (Stage 5) tidak punya task
> yang membaca file itu — `DDCClass` di-`MERGE` hanya dari `rels_ddc.json`
> (cuma bawa `book_id` + `ddc_code`). Hasilnya, node `DDCClass` di Neo4j
> hanya punya `code`, `description`-nya `null`. Lihat
> [data_pipeline.md → Stage 4: Gold](data_pipeline.md#stage-4-gold--embedding--graph-mapping)
> untuk detail dan cara perbaikannya.

| Digit | Deskripsi |
|---|---|
| 0 | Ilmu Komputer & Umum |
| 1 | Filsafat & Psikologi |
| 2 | Agama |
| 3 | Ilmu Sosial |
| 4 | Bahasa |
| 5 | Sains & Matematika |
| 6 | Teknologi & Terapan |
| 7 | Seni & Rekreasi |
| 8 | Sastra |
| 9 | Sejarah & Geografi |

### CollectionType

```
(:CollectionType { name: STRING (UNIQUE) })
-- Dari field bronze `jenis_bahan`, mis. "Monograf", "SumberElektronik"
```

### Vibe / Setting / Character (LLM-extracted, open-vocabulary)

```
(:Vibe      { name: STRING (UNIQUE) })
(:Setting   { name: STRING (UNIQUE) })
(:Character { name: STRING (UNIQUE) })
```

Diisi oleh `silver1.py` untuk **semua buku dengan `abstract_clean` valid**
(bukan hanya fiksi). LLM (Ollama, `format="json"`, `temperature=0`) diminta
maks 5 vibes, 3 settings, 5 characters per buku — nilai apa pun yang
relevan dari teks, tidak dibatasi daftar tetap.

---

## Constraints & Index

**File**: [data_pipeline/utils/ingest_neo4j.py](../data_pipeline/utils/ingest_neo4j.py)

```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (b:Book) REQUIRE b.book_id IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (br:Branch) REQUIRE br.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (p:Publisher) REQUIRE p.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (ddc:DDCClass) REQUIRE ddc.code IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (l:Language) REQUIRE l.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (ct:CollectionType) REQUIRE ct.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (v:Vibe) REQUIRE v.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (s:Setting) REQUIRE s.name IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (ch:Character) REQUIRE ch.name IS UNIQUE

CREATE VECTOR INDEX book_vector_index IF NOT EXISTS
FOR (m:Book) ON (m.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 384,
  `vector.similarity_function`: 'cosine'
}}
```

> Statistik konkret (jumlah node/relasi per tipe) sengaja tidak dicantumkan
> di sini — angka di versi dokumen sebelumnya berasal dari skema lama
> (sebelum DDCClass/Language/City/CollectionType ada dan sebelum SIMILAR_TO
> dihapus) dan sudah tidak relevan. Setelah re-ingestion dengan pipeline
> saat ini, jalankan `MATCH (n) RETURN labels(n)[0], count(*)` langsung di
> Neo4j untuk angka yang akurat.

---

## Cypher Templates

**File**: [shared/schema/cypher_templates.py](../shared/schema/cypher_templates.py) — 24 template statis, tidak ada Text2Cypher/LLM yang menyusun query secara dinamis (bebas halusinasi struktur graf).

### 1. Single-Hop (11 template)

Query langsung per node type, semua mengembalikan `book` + relasi ter-enrich:

`books_by_category`, `books_by_branch`, `books_by_author`, `books_by_publisher`,
`books_by_vibe`, `books_by_setting`, `books_by_character`, `books_by_ddc`,
`books_by_language`, `books_by_collection_type`, `books_by_publisher_city`

### 2. Two-Hop Intersection (8 template)

`books_by_vibe_and_setting`, `books_by_vibe_and_category`,
`books_by_setting_and_category`, `books_by_author_and_vibe`,
`books_by_author_and_setting`, `books_by_author_and_category`,
`books_by_ddc_and_branch`, `books_by_collection_type_and_category`

### 3. Three-Hop (1 template)

`books_by_vibe_and_setting_and_category` — triple intersection vibe+setting+category.

### 4. Collaborative (4 template)

Pattern Book→Entity←Book (cari buku lain yang berbagi atribut dengan buku referensi):

| Template | Hop | Pola |
|---|---|---|
| `books_sharing_vibe_with` | 3 | `Book1-[:HAS_VIBE]->Vibe<-[:HAS_VIBE]-Book2` |
| `books_sharing_vibe_with_setting` | 4 | + filter `Book2-[:HAS_SETTING]->Setting` |
| `books_sharing_ddc_with` | 3 | `Book1-[:CLASSIFIED_AS]->DDCClass<-[:CLASSIFIED_AS]-Book2` |
| `categories_by_author` | 3 | `Author-[:WROTE]->Book-[:BELONGS_TO]->Category`, agregasi `count(b)` (bukan daftar buku — query reporting) |

### Status Wiring ke Agent

`graph_tool.py`/`GraphSearchTool`/`TOOL_REGISTRY` **tidak ada lagi** di
`agent/` (file itu dihapus saat refactor Vector-Gated ReAct; hanya
bertahan di `legacy/agent_v1/tools/` dan `legacy/agent_v2/tools/`). Katalog
produksi saat ini adalah `CYPHER_TOOLS` di
[agent/tools/tools_catalog.py](../agent/tools/tools_catalog.py) — semua 24
template di atas sudah punya entri ekuivalen di sana (nama tool sama),
ditambah 7 tool utility baru (`search_similar_runtime`, `filter_by_branch`,
`filter_by_collection_type`, `filter_by_language`, `enrich_books`,
`lookup_by_title`, `titles_to_ids`) yang tidak ada di `cypher_templates.py`
— total 31 tool. Tiga di antaranya (`search_similar_runtime`,
`enrich_books`, `titles_to_ids`) ada di katalog tapi **belum diekspos** ke
action space Reasoner saat ini — lihat
[agent_workflow.md → Tool Registry](agent_workflow.md#tool-registry).

`categories_by_author` sengaja diperlakukan beda: return shape-nya
(`{category, book_count}`) tidak cocok dengan model pool buku, jadi tool ini
**tidak menambah apapun ke pool** — hasilnya hanya disuntikkan sebagai teks
observation ke scratchpad Reasoner (`NON_BOOK_TOOLS` di
`agent/nodes/tool_executor.py`). Tool lain semua mengikuti kontrak
`(raw_results: list[dict-shaped-like-book], observation: str)`.

`BookNode` ([state.py](../agent/core/state.py)) sekarang juga punya field
`language` dan `edisi` — sebelumnya properti ini SUDAH ada di node Neo4j
(`b.language`, `b.edisi` diisi `ingest_neo4j.py`) tapi `parse_book_node()`
diam-diam membuangnya karena tidak ada field yang menampungnya. Tanpa fix
ini, `books_by_language` akan menemukan buku yang benar tapi
Reasoner/Responder tidak akan pernah melihat bahasanya di pool.

### Contoh Template (2-Hop Intersection)

```cypher
-- books_by_vibe_and_setting
MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
      (b)-[:HAS_SETTING]->(s:Setting)
WHERE toLower(v.name) CONTAINS toLower($vibe)
  AND toLower(s.name) CONTAINS toLower($setting)
WITH b LIMIT 15
OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
OPTIONAL MATCH (b)-[:HAS_SETTING]->(s2:Setting)
RETURN
    properties(b) AS book,
    collect(DISTINCT {name: a.name}) AS authors,
    collect(DISTINCT {name: br.name}) AS branches,
    collect(DISTINCT {name: v2.name}) AS vibes,
    collect(DISTINCT {name: s2.name}) AS settings
```

### Contoh Template (Collaborative — shared DDC)

```cypher
-- books_sharing_ddc_with
MATCH (b1:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass)<-[:CLASSIFIED_AS]-(b2:Book)
WHERE toLower(b1.title) CONTAINS toLower($title)
  AND b1 <> b2
WITH b2, ddc LIMIT 10
OPTIONAL MATCH (a:Author)-[:WROTE]->(b2)
OPTIONAL MATCH (b2)-[:AVAILABLE_AT]->(br:Branch)
OPTIONAL MATCH (b2)-[:BELONGS_TO]->(c:Category)
RETURN
    properties(b2) AS book,
    ddc.code AS shared_ddc,
    collect(DISTINCT {name: a.name}) AS authors,
    collect(DISTINCT {name: br.name}) AS branches,
    collect(DISTINCT {name: c.name}) AS categories
```

---

## Runtime Similarity (pengganti SIMILAR_TO)

**File**: [agent/tools/tools_catalog.py](../agent/tools/tools_catalog.py)
(`search_similar_runtime` entry — `agent/tools/graph_tool.py` yang dulu
menaunginya sudah dihapus, lihat [Status Wiring ke Agent](#status-wiring-ke-agent))

Tidak ada edge pre-computed. Kemiripan dihitung saat query, lewat
`db.index.vector.queryNodes('book_vector_index', ...)` atas embedding Book
target:

```cypher
-- search_similar_runtime (disederhanakan)
MATCH (target:Book)
WHERE toLower(target.title) CONTAINS toLower($title)
  AND target.embedding IS NOT NULL
WITH target ORDER BY size(target.title) ASC LIMIT 1
CALL db.index.vector.queryNodes('book_vector_index', $raw_k, target.embedding)
YIELD node AS b, score
WHERE b.book_id <> target.book_id AND score >= $min_score
-- ... enrichment OPTIONAL MATCH (author, branch, vibe, setting, category)
RETURN properties(b) AS book, score, 'runtime' AS source, ...
ORDER BY score DESC LIMIT $top_k
```

> Tidak ada variant `_with_filters` di katalog saat ini — `search_similar_runtime`
> hanya menerima `{title, raw_k, min_score, top_k}`, tanpa filter
> vibe/setting/category/branch tambahan. Tool ini juga **belum diekspos**
> ke action space Reasoner (lihat
> [agent_workflow.md → Tool Registry](agent_workflow.md#tool-registry)) —
> query "buku mirip X" saat ini ditangani via vector front-door biasa,
> bukan tool ini.

---

## Pydantic Model: BookNode

**File**: [agent/core/state.py](../agent/core/state.py)

Representasi Python dari node Book beserta relasinya — dipakai di seluruh
agent (pool kandidat, `curated_context`, audit Responder):

```python
class BookNode(BaseModel):
    # Core properties
    book_id: str
    title: str
    isbn_13: Optional[str]
    pub_year: Optional[int]
    total_pages: Optional[int]
    abstract_clean: Optional[str]
    is_fiction: bool
    cover_url: Optional[str]
    ddc_class: Optional[str]          # kode DDC 3 digit
    language: Optional[str]
    edisi: Optional[str]
    relevance_score: float            # 0.0 - 1.0, clamp via validator

    # Relasi ontologi (hasil traversal)
    authors: List[AuthorNode]         # [:WROTE]
    publisher: Optional[PublisherNode]  # [:PUBLISHED_BY]
    categories: List[CategoryNode]    # [:BELONGS_TO]
    branches: List[BranchNode]        # [:AVAILABLE_AT]
    vibes: List[VibeNode]             # [:HAS_VIBE]
    settings: List[SettingNode]       # [:HAS_SETTING]
    characters: List[CharacterNode]   # [:FEATURES_CHARACTER]

    # Computed properties
    @property
    def is_available(self) -> bool: ...   # len(branches) > 0
    @property
    def available_at(self) -> list[str]: ...
    @property
    def author_names(self) -> list[str]: ...
    @property
    def vibe_names(self) -> list[str]: ...
    @property
    def setting_names(self) -> list[str]: ...
```

> **Tidak ada field `similar_to: List[SimilarityEdge]`** — dihapus
> bersamaan dengan relasi `SIMILAR_TO`.
>
> `language`/`edisi` adalah **properti scalar Book sendiri** (bukan relasi
> ke node lain), jadi cukup ditambahkan sebagai field langsung. `City` dan
> `CollectionType` masih **tidak** punya representasi di `BookNode` — kedua
> node itu hanya dipakai sebagai filter masuk (`books_by_publisher_city`,
> `books_by_collection_type`) tapi hasilnya tidak dikembalikan sebagai
> relasi terikat ke buku (sama seperti `branches` belum membawa `address` —
> butuh proyeksi tambahan di Cypher template kalau mau disurfacekan).
