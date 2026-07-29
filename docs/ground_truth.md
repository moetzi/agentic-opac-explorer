# Ground Truth Evaluasi — Skema & Audit Konsistensi

> Sumber data: [`evaluation/ground_truth.json`](../evaluation/ground_truth.json) (100 kueri).
> Dokumen ini mendokumentasikan skema ground truth dan **audit konsistensi** yang
> memverifikasi bahwa setiap entri valid terhadap knowledge graph — sehingga angka
> retrieval (Precision@K, Tool Set Match) dapat dipertahankan di sidang.

## 1. Peran

Ground truth adalah **himpunan relevan** (relevant set) per kueri untuk sistem
rekomendasi buku. Berbeda dari QA faktoid yang punya satu jawaban benar, di sini
beberapa buku bisa sama-sama relevan; maka metrik memakai Precision@K terhadap
`expected_titles`, bukan Exact Match. Ground truth dikonsumsi oleh
[`evaluation/run_comparative_evaluation.py`](../evaluation/run_comparative_evaluation.py)
(Phase 1, metrik offline) dan menjadi acuan Phase 2 (LLM-as-judge).

## 2. Skema per entri

| Field | Tipe | Keterangan |
|---|---|---|
| `id` | str | `Q01`–`Q100` |
| `query` | str | pertanyaan pengguna (Bahasa Indonesia) |
| `query_type` | str | salah satu dari 22 tipe (§3) |
| `hop_count` | int | jumlah hop traversal (1–3) |
| `expected_tools` | list[str] | tool graph yang seharusnya dipanggil (acuan Tool Set Match) |
| `expected_titles` | list[str] | judul buku yang dianggap relevan (acuan Precision@K) |
| `expected_answer_contains` | list[str] | kata kunci yang harus ada di jawaban (proxy Answer Relevance) |
| `reference_answer` | str | jawaban acuan naratif |

## 3. Komposisi

- **100 kueri**, **22 tipe**, distribusi hop: **1-hop 42, 2-hop 42, 3-hop 16**.
- `expected_titles`: total **3.053 judul**, per kueri min 3 / maks 156 / rata-rata ≈ 30.

| Tipe kueri | hop | n | Tipe kueri | hop | n |
|---|---|---|---|---|---|
| 1-hop_author | 1 | 5 | 2-hop_author_category | 2 | 4 |
| 1-hop_category | 1 | 5 | 2-hop_author_setting | 2 | 4 |
| 1-hop_character | 1 | 4 | 2-hop_author_vibe | 2 | 4 |
| 1-hop_ddc | 1 | 5 | 2-hop_collectiontype_category | 2 | 4 |
| 1-hop_language | 1 | 3 | 2-hop_ddc_branch | 2 | 4 |
| 1-hop_publisher_city | 1 | 4 | 2-hop_setting_category | 2 | 4 |
| 1-hop_setting | 1 | 5 | 2-hop_vibe_category | 2 | 6 |
| 1-hop_vibe | 1 | 5 | 2-hop_vibe_setting | 2 | 6 |
| runtime_similarity | 1 | 6 | branch_filter_author | 2 | 2 |
| collaborative_shared_ddc | 3 | 4 | branch_filter_vibe | 2 | 4 |
| collaborative_shared_vibe | 3 | 5 | 3-hop_vibe_setting_category | 3 | 7 |

Tipe mencakup pencarian per atribut reliable (author/category/DDC/language/
publisher_city), atribut hasil ekstraksi sinopsis (vibe/setting/character),
kombinasi multi-atribut, filter cabang, collaborative ("X sama dengan judul Y"),
dan similarity ("mirip judul X"). Lihat [`docs/tools_catalog.md`](tools_catalog.md).

## 4. Audit konsistensi (100 kueri)

Audit menguji apakah ground truth **konsisten dengan knowledge graph**, agar
Precision@K mengukur kualitas retrieval — bukan ketidakcocokan antara dua sumber.
Metode (tanpa menjalankan agen, langsung ke Neo4j):

1. **Eksistensi** — setiap `expected_title` diresolusi ke node `:Book`.
2. **Coverage atribut** — untuk atribut yang ditanya kueri, nilai dominan di antara
   buku ekspektasi diinferensi (provenance-agnostic) lalu dihitung fraksi buku
   ekspektasi yang benar-benar mengusung nilai itu di graf.

### Hasil

| Cek | Hasil |
|---|---|
| Judul ekspektasi total | 3.053 |
| Teresolusi di graf | **3.053 (100%)** |
| Judul hilang / halusinasi | **0** |
| Coverage atribut per kueri | **≥ 80%**, mayoritas ~100% |
| Entri ter-flag rusak | **0 / 100** |

**Kesimpulan: ground truth BERSIH.** Setiap judul ekspektasi ada di graf dan
benar-benar mengusung atribut yang ditanyakan (mis. Q40 `setting='desa'`:100%,
Q98 `vibe='komedi'`:100%, Q99 `vibe='sejarah'`:100%). Tidak ada entri yang perlu
diperbaiki.

## 5. Temuan: kegagalan retrieval bersumber dari TOOL, bukan ground truth

Audit ini penting karena mengoreksi hipotesis awal ("beberapa kueri gagal karena
ground truth-nya meleset"). Kenyataannya, kueri yang gagal punya ground truth yang
**benar** — masalahnya ada di tool retrieval. Contoh kanonik **Q40**
("buku berlatar desa"): ke-36 judul ekspektasi semuanya bertag `setting='desa'`,
namun tool `books_by_setting` memakai `CONTAINS "desa"` yang juga menangkap
`'pedesaan'` (122 buku) lalu `LIMIT 15` tanpa urutan → 15 buku pedesaan acak
menggeser habis buku "desa" (P@3 = 0). Perbaikannya di lapisan tool
(exact-match-first, lihat [`tools_catalog.md` §5](tools_catalog.md)), **bukan** di
ground truth: setelah diperbaiki Q40 → P@3 = 1.0.

Sisa kegagalan yang bukan presisi-tool juga bukan cacat ground truth, melainkan:
- **`runtime_similarity` Q97** — buku referensi tak punya embedding memadai (celah data).
- **Q13** — planner (model kecil) kadang salah mem-parse "Fiksi Indonesia" sebagai author.

## 6. Metrik yang mengonsumsi ground truth

| Metrik | Field GT | Formula |
|---|---|---|
| Precision@K (K=3,5) | `expected_titles` | \|retrieved∩expected\| / K |
| Tool Set Match | `expected_tools` | \|called∩expected\| / \|expected\| − penalti filter destruktif |
| Answer Contains (proxy) | `expected_answer_contains` | fraksi keyword yang muncul di jawaban |
| Title Faithfulness (proxy) | — (konteks + query) | fraksi judul terkutip yang tergrounding |

Detail metrik: [`evaluation/metrics.py`](../evaluation/metrics.py) dan
[`docs/evaluasi.md`](evaluasi.md). Catatan bias `answer_contains` sebagai proxy
offline dibahas di [`docs/analisis.md` §7](analisis.md).

## 7. Regenerasi

Skema lama (20 kueri, `expected_book_ids`) di
[`evaluation/create_ground_truth.py`](../evaluation/create_ground_truth.py) sudah
**usang** dan tidak menghasilkan `ground_truth.json` versi 100-kueri sekarang.
`ground_truth.json` adalah artefak final; audit di §4 dapat dijalankan ulang kapan
pun langsung terhadap graf untuk memverifikasi konsistensi.
