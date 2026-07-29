import re
import pandas as pd
from pathlib import Path

BRONZE_DIR = Path(__file__).resolve().parent.parent / "bronze"
SILVER_DIR = Path(__file__).resolve().parent

# --- 2. MODULAR TRANSFORMATION FUNCTIONS ---

_NULL_PLACEHOLDERS = {"", "-", ".", "n/a", "n/a.", "null", "none", "tidak ada data", "tidak ada data."}

def _normalize_null(val):
    """Coerce empty/placeholder strings to None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return None if s.lower() in _NULL_PLACEHOLDERS else s


def check_fiksi(holdings):
    """Tentukan fiksi berdasarkan DDC kelas 800 atau penanda lokal pada call_number."""
    if not holdings or not isinstance(holdings, list):
        return False
    for holding in holdings:
        call_number = str(holding.get("call_number", "")).strip()
        if not call_number:
            continue
        match = re.search(r'^\d{3}', call_number)
        if match and match.group().startswith('8'):
            return True
        if re.search(r'\b(f|fik|fiksi|fic|fiction)\b', call_number.lower()):
            return True
    return False


def extract_ddc(holdings):
    """Ekstrak kode DDC 3 digit dari holdings. Kembalikan (ddc_class, ddc_division) atau (None, None)."""
    if not holdings or not isinstance(holdings, list):
        return None, None
    for holding in holdings:
        call_number = str(holding.get("call_number", "")).strip()
        match = re.search(r'(\d{3})', call_number)
        if match:
            code = match.group(1)
            return code, code[0]
    return None, None


def categorize_abstract(abs_text):
    if pd.isna(abs_text) or str(abs_text).strip() == "":
        return "Kosong/Null"
    abs_clean = str(abs_text).lower().strip()
    placeholders = ["tidak ada data", "tidak ada data.", "-", ".", "n/a", "null"]
    if abs_clean in placeholders or not re.search('[a-zA-Z0-9]', abs_clean):
        return "Teks Placeholder (Sampah)"
    return "Valid/Berkualitas" if len(abs_clean) >= 50 else "Terlalu Pendek (< 50 char)"


# REFACTOR: Pisahkan clean abstract dari raw. Raw selalu dipreservasi,
# clean menjadi None jika kualitas abstract tidak valid — mencegah noise di embedding.
def get_abstract_clean(abs_text, abs_qual):
    """Kembalikan teks abstrak hanya jika kualitasnya valid, selainnya None."""
    if abs_qual == "Valid/Berkualitas":
        return str(abs_text).strip()
    return None


DAFTAR_ROLE = [
    "editor bahasa indonesia", "editor bahasa mandarin", "editor dan proofreader",
    "ilustrasi sampul", "penulis pendamping", "proofreader", "penerjemah",
    "penyunting", "ilustrator", "pengarang", "ilustrasi", "penyusun",
    "penulis", "editor"
]

def process_authors_modular(author_raw):
    if not author_raw or author_raw == "-":
        return []

    entries = [a.strip() for a in str(author_raw).split(';')]
    results = []

    for entry in entries:
        if not entry:
            continue

        role = "penulis" # Fallback default
        name = entry

        # 1. Cek format "Role: Nama"
        if ":" in name:
            parts = name.split(":", 1)
            role = parts[0].strip().lower()
            name = parts[1].strip()

        # 2. Tangkap role dari dalam kurung biasa () ATAU kurung siku []
        role_match = re.search(r'[\(\[]([^()\[\]]+)[\)\]]', name)
        if role_match:
            role = role_match.group(1).lower().strip()
            # Hapus kurung beserta isinya dari nama
            name = re.sub(r'[\(\[][^()\[\]]+[\)\]]', '', name).strip()

        # 3. Deteksi role yang digabung dengan koma (misal: "John Doe, penyunting")
        name_lower = name.lower()
        for r in DAFTAR_ROLE:
            # Cari apakah ada role dari list di dalam nama
            if re.search(rf'\b{r}\b', name_lower):
                role = r
                # Hapus kata role tersebut dari string nama (case-insensitive)
                name = re.sub(rf'(?i)\b{r}\b', '', name)
                break

        # 4. Bersihkan koma atau spasi menggantung akibat penghapusan role
        # Contoh: "John Doe, " akan menjadi "John Doe"
        name = name.strip(',- .')

        # 5. Resolusi Entitas: Balik nama "Belakang, Depan" menjadi "Depan Belakang"
        # Karena role sudah dihapus di langkah 3, koma yang tersisa pasti milik format nama
        if "," in name:
            parts = name.split(",", 1)
            if len(parts) == 2:
                name = f"{parts[1].strip()} {parts[0].strip()}"

        # 6. Pembersihan final (huruf kapital dan spasi ganda)
        name = re.sub(r'\s+', ' ', name).strip().title()

        # Cegah string kosong masuk ke hasil
        if name:
            results.append({"name": name, "role": role})

    return results


def process_isbn_modular(isbn_raw):
    res = {"isbn10": None, "isbn13": None}
    if not isbn_raw or isbn_raw == "-":
        return res
    parts = re.split(r'[;\s]+', str(isbn_raw))
    for part in parts:
        clean = re.sub(r'[^0-9X]', '', part.upper())
        if len(clean) == 13 and clean.startswith(('978', '979')):
            res["isbn13"] = clean  # type: ignore
        elif len(clean) == 10:
            res["isbn10"] = clean  # type: ignore
    return res


def process_publisher_modular(pub_raw):
    res = {"city": None, "publisher": None, "year": None}
    if not pub_raw or pub_raw == "-":
        return res
    try:
        if ":" in pub_raw:
            res["city"], rest = [x.strip() for x in pub_raw.split(":", 1)]
        else:
            rest = pub_raw
        if "," in rest:
            p_part, y_part = [x.strip() for x in rest.rsplit(",", 1)]
            res["publisher"] = p_part
            year_match = re.search(r'\d{4}', y_part)
            res["year"] = int(year_match.group()) if year_match else None  # type: ignore
        else:
            res["publisher"] = rest
    except Exception:
        pass
    return res


def process_physical_description(text):
    res = {"pages": None, "dimension": None}
    if not text or text == "-":
        return res
    page_match = re.search(r'(\d+)\s*(?:hlm|halaman)', text.lower())
    if page_match:
        res["pages"] = int(page_match.group(1))  # type: ignore
    dim_match = re.search(r'(\d+[.,]?\d*)\s*cm', text.lower())
    if dim_match:
        res["dimension"] = dim_match.group(1).replace(',', '.') + " cm"  # type: ignore
    return res


# --- 3. MAIN WRAPPER ---

def transform_to_silver(row):
    holdings = row.get('holdings') or []
    authors_data = process_authors_modular(row['authors_raw'])
    isbn_data = process_isbn_modular(row['isbn'])
    pub_data = process_publisher_modular(row['publisher_raw'])
    phys_data = process_physical_description(row['deskripsi_fisik'])
    abs_qual = categorize_abstract(row['abstrak'])

    abstract_raw = row['abstrak'] if not pd.isna(row['abstrak']) else None
    abstract_clean = get_abstract_clean(row['abstrak'], abs_qual)
    is_fiction = check_fiksi(holdings)
    ddc_class, ddc_division = extract_ddc(holdings)

    cat_raw = str(row['category_raw']).strip()
    categories = (
        sorted([c.strip().title() for c in cat_raw.split('/') if c.strip()])
        if cat_raw and cat_raw not in ["-", "null", "none"]
        else []
    )

    available_branches = sorted(set(
        h['branch_name'] for h in holdings if 'branch_name' in h
    ))

    # branches_metadata: {name, address} dedup by name — alamat dipakai gold.py
    # untuk mengisi Branch.address (dideklarasikan di neo4j_schema.py tapi
    # sebelumnya tidak pernah dipopulasikan dari pipeline).
    _branch_addr: dict[str, str | None] = {}
    for h in holdings:
        name = h.get('branch_name')
        if not name or name in _branch_addr:
            continue
        _branch_addr[name] = _normalize_null(h.get('branch_address'))
    branches_metadata = [
        {"name": name, "address": addr} for name, addr in sorted(_branch_addr.items())
    ]

    def safe_int(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    silver = {
        "book_id": row['doc_id'],
        "title": row['title'].strip(),
        "authors": [a['name'] for a in authors_data],
        "authors_metadata": authors_data,
        "categories": categories,
        "isbn_10": isbn_data['isbn10'],
        "isbn_13": isbn_data['isbn13'],
        "pub_city": pub_data['city'],
        "pub_name": pub_data['publisher'],
        "pub_year": safe_int(pub_data['year']),
        "total_pages": safe_int(phys_data['pages']),
        "dimensions": phys_data['dimension'],
        "ddc_class": ddc_class,
        "ddc_division": ddc_division,
        "abstract": abstract_raw,
        "abstract_clean": abstract_clean,
        "abs_qual": abs_qual,
        "is_fiction": is_fiction,
        "available_branches": available_branches,
        "branches_metadata": branches_metadata,
        "cover_url": row['cover_url'],
        # Raw fields copied from bronze
        "language": _normalize_null(row.get('language')),
        "edisi": _normalize_null(row.get('edisi')),
        "jenis_bahan": _normalize_null(row.get('jenis_bahan')),
        "pernyataan_seri": _normalize_null(row.get('pernyataan_seri')),
        "judul_alternatif": _normalize_null(row.get('judul_alternatif')),
        "source_url": _normalize_null(row.get('source_url')),
        "has_cover": bool(row.get('has_cover', False)),
    }

    return pd.Series(silver)

# --- 4. EXECUTION LOOP ---

# REFACTOR: Filter mask_fiksi_valid dihapus.
# Buku fiksi tanpa abstrak valid tetap masuk silver dengan abstract_clean=None
# dan fiction_keywords kosong. Data tidak dibuang — masih berguna untuk entity resolution.
# Filtering agresif seharusnya terjadi di gold layer berdasarkan kebutuhan use case.

if __name__ == "__main__":
    bronze_files = sorted(BRONZE_DIR.glob("books_raw_part_*.jsonl"))

    if not bronze_files:
        print(f"[!] Tidak ada file .jsonl yang ditemukan di {BRONZE_DIR}.")
    else:
        print(f"[*] Ditemukan {len(bronze_files)} file untuk diproses dari {BRONZE_DIR}.")
        stats = {"total": 0, "saved": 0}

        for bronze_path in bronze_files:
            print(f"\n[*] Processing {bronze_path.name}...")

            silver_path = SILVER_DIR / bronze_path.name.replace("raw", "silver")

            try:
                df = pd.read_json(bronze_path, lines=True)
                stats["total"] += len(df)

                mask_monograf = df['jenis_bahan'].str.lower() == 'monograf'
                df_filtered = df[mask_monograf].copy()

                if not df_filtered.empty:
                    df_silver = df_filtered.apply(transform_to_silver, axis=1)

                    df_silver['pub_year'] = df_silver['pub_year'].astype('Int64')
                    df_silver['total_pages'] = df_silver['total_pages'].astype('Int64')

                    df_silver.to_json(silver_path, orient='records', lines=True, force_ascii=False)

                    stats["saved"] += len(df_silver)
                    print(f"    [+] Tersimpan: {silver_path}")

            except Exception as e:
                print(f"[!] Error {bronze_path.name}: {e}")

        print(f"\n[DONE] Saved {stats['saved']}/{stats['total']} books.")
