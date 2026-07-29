import pandas as pd
import torch
import json
import os
import gc
from pathlib import Path
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

SILVER_DIR = Path(__file__).resolve().parent.parent / "silver"
GOLD_DIR = Path(__file__).resolve().parent
GRAPH_DIR = GOLD_DIR / "graph"

# --- SETUP MODEL ---
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"[*] Using device: {device}")

# REFAKTOR: Ganti model ke E5 Indo (Multilingual, Bahasa Indonesia Optimal)
model_name = 'LazarusNLP/all-indo-e5-small-v4'
hf_token = os.getenv("HF_TOKEN")
embedding_model = SentenceTransformer(model_name, device=device, token=hf_token)

# DDC division code → label (kelas utama Dewey)
_DDC_LABELS = {
    "0": "Ilmu Komputer & Umum", "1": "Filsafat & Psikologi",
    "2": "Agama", "3": "Ilmu Sosial", "4": "Bahasa",
    "5": "Sains & Matematika", "6": "Teknologi & Terapan",
    "7": "Seni & Rekreasi", "8": "Sastra", "9": "Sejarah & Geografi",
}


# --- CORE TRANSFORMATION FUNCTIONS ---

def build_content_for_embedding(row) -> str:
    """Feature selection untuk embedding. Dipanggil di gold, bukan silver."""
    parts = [
        f"Judul: {row['title']}",
        f"Penulis: {', '.join(row['authors'])}" if row.get('authors') else None,
        f"Kategori: {', '.join(row['categories'])}" if row.get('categories') else None,
        f"DDC: {row['ddc_class']}" if row.get('ddc_class') else None,
        f"Sinopsis: {row['abstract_clean']}" if row.get('abstract_clean') else None,
    ]
    return ". ".join(p for p in parts if p)


def generate_embeddings(texts):
    if not texts:
        return []
    prefixed = [f"passage: {t}" for t in texts]
    return embedding_model.encode(prefixed, batch_size=32, show_progress_bar=True).tolist()


def map_graph_structure(df):
    nodes_book = []
    rels_written, rels_category, rels_published, rels_available = [], [], [], []
    rels_vibe, rels_setting, rels_character = [], [], []
    rels_ddc, rels_language, rels_collection_type = [], [], []

    authors_set, categories_set, branches_set = set(), set(), set()
    publishers_set = set()   # (name, city)
    vibes_set, settings_set, characters_set = set(), set(), set()
    ddc_set = set()          # (code, description)
    languages_set = set()
    collection_types_set = set()

    for _, row in df.iterrows():
        b_id = str(row['book_id'])

        # 1. Node Book — termasuk abstract_clean dan ddc_class
        nodes_book.append({
            "book_id": b_id,
            "title": str(row['title']),
            "isbn_13": str(row['isbn_13']) if row.get('isbn_13') else None,
            "pub_year": int(row['pub_year']) if pd.notna(row.get('pub_year')) else None,
            "total_pages": int(row['total_pages']) if pd.notna(row.get('total_pages')) else None,
            "cover_url": str(row.get('cover_url') or ""),
            "is_fiction": bool(row.get('is_fiction', False)),
            "abstract_clean": str(row['abstract_clean']) if row.get('abstract_clean') else None,
            "ddc_class": str(row['ddc_class']) if row.get('ddc_class') else None,
            "edisi": str(row['edisi']) if row.get('edisi') else None,
            "language": str(row['language']) if row.get('language') else None,
            "embedding": row['embedding'],
        })

        # 2. Author
        for auth in (row.get('authors_metadata') or []):
            authors_set.add(auth['name'])
            rels_written.append({"book_id": b_id, "author_name": auth['name'], "role": auth.get('role', 'penulis')})

        # 3. Category
        for cat in (row.get('categories') or []):
            categories_set.add(cat)
            rels_category.append({"book_id": b_id, "category_name": cat})

        # 4. Publisher + City
        if row.get('pub_name'):
            pub_name = str(row['pub_name'])
            pub_city = str(row['pub_city']) if row.get('pub_city') else None
            publishers_set.add((pub_name, pub_city))
            rels_published.append({"book_id": b_id, "publisher_name": pub_name, "city": pub_city})

        # 5. Branch (+ address, dari silver.py branches_metadata)
        for br in (row.get('branches_metadata') or []):
            branches_set.add((br['name'], br.get('address')))
            rels_available.append({
                "book_id": b_id, "branch_name": br['name'], "address": br.get('address'),
            })

        # 6. DDCClass
        ddc_code = str(row['ddc_class']) if row.get('ddc_class') else None
        if ddc_code:
            division = ddc_code[0] if ddc_code else None
            desc = _DDC_LABELS.get(division, "Tidak Diketahui") if division else "Tidak Diketahui"
            ddc_set.add((ddc_code, desc))
            rels_ddc.append({"book_id": b_id, "ddc_code": ddc_code})

        # 7. Language
        lang = str(row['language']) if row.get('language') else None
        if lang:
            languages_set.add(lang)
            rels_language.append({"book_id": b_id, "language": lang})

        # 8. CollectionType (jenis_bahan)
        ctype = str(row['jenis_bahan']) if row.get('jenis_bahan') else None
        if ctype:
            collection_types_set.add(ctype)
            rels_collection_type.append({"book_id": b_id, "collection_type": ctype})

        # 9. Vibe / Setting / Character — dari silver1.py enrichment
        for v in (row.get('vibes') or []):
            if v:
                vibes_set.add(v)
                rels_vibe.append({"book_id": b_id, "vibe_name": v})
        for s in (row.get('setting') or []):
            if s:
                settings_set.add(s)
                rels_setting.append({"book_id": b_id, "setting_name": s})
        for c in (row.get('characters') or []):
            if c:
                characters_set.add(c)
                rels_character.append({"book_id": b_id, "character_name": c})

    return {
        "nodes_book": nodes_book,
        "nodes_author": [{"name": a} for a in authors_set],
        "nodes_category": [{"name": c} for c in categories_set],
        "nodes_publisher": [{"name": p[0], "city": p[1]} for p in publishers_set],
        "nodes_branch": [{"name": b[0], "address": b[1]} for b in branches_set],
        "nodes_ddc": [{"code": d[0], "description": d[1]} for d in ddc_set],
        "nodes_language": [{"name": l} for l in languages_set],
        "nodes_collection_type": [{"name": ct} for ct in collection_types_set],
        "nodes_vibe": [{"name": v} for v in vibes_set],
        "nodes_setting": [{"name": s} for s in settings_set],
        "nodes_character": [{"name": c} for c in characters_set],
        "rels_written": rels_written,
        "rels_category": rels_category,
        "rels_published": rels_published,
        "rels_available": rels_available,
        "rels_ddc": rels_ddc,
        "rels_language": rels_language,
        "rels_collection_type": rels_collection_type,
        "rels_vibe": rels_vibe,
        "rels_setting": rels_setting,
        "rels_character": rels_character,
    }


# --- 3. PROCESSING WRAPPER ---
def process_single_dataframe(df):
    """Fungsi tunggal untuk embedding dan mapping."""
    print(f"[*] Membangun content_for_embedding untuk {len(df)} records...")
    df['content_for_embedding'] = df.apply(build_content_for_embedding, axis=1)
    print(f"[*] Menghasilkan embeddings...")
    df['embedding'] = generate_embeddings(df['content_for_embedding'].tolist())
    graph_data = map_graph_structure(df)
    return df, graph_data


# --- 4. EXECUTION MODES ---
def run_test_single_file(filename="books_silver_enriched_part_001.jsonl"):
    """Fungsi test diarahkan langsung ke salah satu partisi."""
    print(f"[*] TESTING MODE: Memproses {filename}...")
    try:
        df = pd.read_json(SILVER_DIR / filename, lines=True).head(100)

        df_gold, graph_data = process_single_dataframe(df)

        test_dir = GOLD_DIR / "test"
        test_dir.mkdir(parents=True, exist_ok=True)

        df_gold.to_parquet(test_dir / "test_gold.parquet", index=False)

        with open(test_dir / "nodes_book_sample.json", "w", encoding="utf-8") as f:
            json.dump(graph_data['nodes_book'], f, ensure_ascii=False)

        print(f"[SUCCESS] Test selesai. Cek folder '{test_dir}'")

    except Exception as e:
        print(f"[!] Error saat test: {e}")

def run_batch_gold():
    """Fungsi utama untuk memproses seluruh data silver menjadi gold secara hemat RAM."""
    print("[*] BATCH MODE: Memulai proses Gold Layer (Memory Optimized)...")

    target_files = sorted(SILVER_DIR.glob("books_silver_enriched_part_*.jsonl"))
    if not target_files:
        print(f"[!] Tidak ada file .jsonl yang ditemukan di {SILVER_DIR}.")
        return

    print(f"[*] Ditemukan {len(target_files)} partisi file silver.")

    # Siapkan penampung global
    master_df_list = []
    global_graph = {
        "nodes_book": [],
        "rels_written": [], "rels_category": [], "rels_published": [],
        "rels_available": [], "rels_ddc": [], "rels_language": [],
        "rels_collection_type": [], "rels_vibe": [], "rels_setting": [],
        "rels_character": [],
    }

    # Set global untuk deduplikasi lintas file
    authors_set, categories_set, branches_set = set(), set(), set()
    publishers_set = set()
    ddc_set, languages_set, collection_types_set = set(), set(), set()
    vibes_set, settings_set, characters_set = set(), set(), set()

    for part in target_files:
        try:
            print(f"\n[*] Memproses file: {part.name}")
            df_part = pd.read_json(part, lines=True)

            # 1. Buat content_for_embedding dan generate embedding
            df_part['content_for_embedding'] = df_part.apply(build_content_for_embedding, axis=1)
            df_part['embedding'] = generate_embeddings(df_part['content_for_embedding'].tolist())

            # 2. Hapus teks panjang yang tidak lagi dibutuhkan untuk hemat RAM
            df_part.drop(columns=['content_for_embedding', 'abstract'], inplace=True, errors='ignore')

            # 3. Ekstrak Graph
            part_graph = map_graph_structure(df_part)

            # Gabungkan list (Buku dan Relasi)
            global_graph["nodes_book"].extend(part_graph["nodes_book"])
            for key in ("rels_written", "rels_category", "rels_published", "rels_available",
                        "rels_ddc", "rels_language", "rels_collection_type",
                        "rels_vibe", "rels_setting", "rels_character"):
                global_graph[key].extend(part_graph[key])

            # Gabungkan Set (Deduplikasi otomatis)
            authors_set.update(a['name'] for a in part_graph["nodes_author"])
            categories_set.update(c['name'] for c in part_graph["nodes_category"])
            publishers_set.update((p['name'], p['city']) for p in part_graph["nodes_publisher"])
            branches_set.update((b['name'], b['address']) for b in part_graph["nodes_branch"])
            ddc_set.update((d['code'], d['description']) for d in part_graph["nodes_ddc"])
            languages_set.update(l['name'] for l in part_graph["nodes_language"])
            collection_types_set.update(ct['name'] for ct in part_graph["nodes_collection_type"])
            vibes_set.update(v['name'] for v in part_graph["nodes_vibe"])
            settings_set.update(s['name'] for s in part_graph["nodes_setting"])
            characters_set.update(c['name'] for c in part_graph["nodes_character"])

            master_df_list.append(df_part)

            del df_part
            del part_graph
            gc.collect()

        except Exception as e:
            print(f"[!] Gagal memproses {part.name}: {e}")

    # --- SETELAH SEMUA FILE SELESAI ---
    global_graph["nodes_author"] = [{"name": a} for a in authors_set]
    global_graph["nodes_category"] = [{"name": c} for c in categories_set]
    global_graph["nodes_publisher"] = [{"name": p[0], "city": p[1]} for p in publishers_set]
    global_graph["nodes_branch"] = [{"name": b[0], "address": b[1]} for b in branches_set]
    global_graph["nodes_ddc"] = [{"code": d[0], "description": d[1]} for d in ddc_set]
    global_graph["nodes_language"] = [{"name": l} for l in languages_set]
    global_graph["nodes_collection_type"] = [{"name": ct} for ct in collection_types_set]
    global_graph["nodes_vibe"] = [{"name": v} for v in vibes_set]
    global_graph["nodes_setting"] = [{"name": s} for s in settings_set]
    global_graph["nodes_character"] = [{"name": c} for c in characters_set]

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)

    # Simpan Parquet
    df_full = pd.concat(master_df_list, ignore_index=True)
    df_full.to_parquet(GOLD_DIR / "books_gold_master.parquet", index=False)

    # Simpan Graph JSON
    for key, data in global_graph.items():
        file_path = GRAPH_DIR / f"{key}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    print(f"\n[DONE] Seluruh data berhasil diproses dengan memori yang dioptimalkan.")

if __name__ == "__main__":
    # Pilih salah satu untuk dijalankan:

    # 1. Jalankan Test dulu:
    # run_test_single_file()

    # 2. Jika sudah mantap, jalankan batch:
    run_batch_gold()
