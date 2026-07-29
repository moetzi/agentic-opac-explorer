import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from utils.minio_client import MinioClient

import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from dotenv import load_dotenv, find_dotenv
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv(find_dotenv())  # Pastikan .env ditemukan dari root project

def get_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Environment variable {key} tidak ditemukan!")
    return value

# DEBUG
print(f"DEBUG: Endpoint dari .env -> {os.getenv('MINIO_ENDPOINT')}")

class BronzeBookETL:
    def __init__(self, minio_client: MinioClient, source_bucket: str, target_bucket: str):
        self.client = minio_client
        self.source_bucket = source_bucket
        self.target_bucket = target_bucket
        self.client.ensure_bucket(self.target_bucket)

    def _get_field(self, soup, label_text):
        """Logika ekstraksi field sesuai skrip asli (FIXED Abstrak)."""
        if label_text == "Abstrak":
            value_div = soup.find("div", class_="col-lg-12 text-break")
            if value_div:
                p = value_div.find("p")
                if p:
                    return p.get_text(" ", strip=True).strip()

        label_p = soup.find("p", class_="fw-bolder", string=lambda s: s and s.strip() == label_text)
        if label_p:
            row = label_p.find_parent("div", class_="row")
            if row:
                col = row.find("div", class_="col-md-8")
                if col:
                    p = col.find("p")
                    return p.get_text(" ", strip=True) if p else ""
        return ""

    def _parse_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        title_tag = soup.select_one("div.product-info h2.title")
        category_tag = soup.select_one("div.product-info p.category")

        return {
            "title": title_tag.get_text(strip=True) if title_tag else "",
            "category_raw": category_tag.get_text(" ", strip=True) if category_tag else "",
            "jenis_bahan": self._get_field(soup, "Jenis Bahan"),
            "judul_alternatif": self._get_field(soup, "Judul Alternatif"),
            "authors_raw": self._get_field(soup, "Pengarang"),
            "edisi": self._get_field(soup, "Edisi"),
            "pernyataan_seri": self._get_field(soup, "Pernyataan Seri"),
            "publisher_raw": self._get_field(soup, "Penerbitan"),
            "language": self._get_field(soup, "Bahasa"),
            "deskripsi_fisik": self._get_field(soup, "Deskripsi Fisik"),
            "isbn": self._get_field(soup, "ISBN"),
            "abstrak": self._get_field(soup, "Abstrak"),
        }

    def _parse_book_cover(self, soup: BeautifulSoup) -> str:
        img_current = soup.find("img", id="current")
        if img_current:
            src = img_current.get('src')
            if isinstance(src, str):
                return src

        cover_selectors = ['img.book-cover', 'img.cover', '.product-image img', 'img[alt*="cover"]']
        for selector in cover_selectors:
            img = soup.select_one(selector)
            if img:
                src = img.get('src')
                if isinstance(src, str):
                    if src.startswith('/'):
                        src = 'https://perpustakaan.jakarta.go.id' + src
                    return src

        return ""

    def _parse_holdings_table(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        holdings = []

        table = soup.find("table", id="eksemplar")
        if table is None:
            return holdings

        tbody = table.find("tbody")
        if tbody is None:
            return holdings

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            branch_name = ""
            branch_address = ""

            if len(cells) > 2:
                branch_cell = cells[2]

                branch_name_tag = branch_cell.find("span", class_="fw-bolder")
                branch_name = branch_name_tag.get_text(strip=True) if branch_name_tag else ""

                branch_texts = branch_cell.get_text("\n", strip=True).split("\n")
                branch_address = " ".join(
                    [t.strip() for t in branch_texts if t.strip() != branch_name]
                ).strip()

            holdings.append({
                "barcode": cells[0].get_text(strip=True),
                "call_number": cells[1].get_text(strip=True),
                "branch_name": branch_name,
                "branch_address": branch_address,
                "availability": cells[6].get_text(" ", strip=True) if len(cells) > 6 else "",
            })

        return holdings
    
    BASE_URL = "https://kios-perpustakaan.jakarta.go.id/catalogue/detail"

    def _extract_source_id(self, key: str) -> str:
        match = re.search(r'(\d+)(?:\.html)?$', key)
        if match:
            return match.group(1)

        fallback = Path(key).stem
        print(f"[WARN] Gagal extract ID dari key: {key}, pakai fallback: {fallback}", flush=True)
        return fallback

    def _build_source_info(self, key: str) -> Dict[str, str]:
        source_id = self._extract_source_id(key)

        return {
            "source_id": source_id,
            "doc_id": f"book_{source_id}",   
            "source_url": f"{self.BASE_URL}/{source_id}"
        }

    def is_empty_abstrak(self, abstrak_text: str) -> bool:
        if not abstrak_text:
            return True

        cleaned = abstrak_text.strip().lower()

        invalid_values = {
            '',
            'tidak ada data',
            'tidak ada data.',
            '-',
            '—',
            'n/a'
        }

        return cleaned in invalid_values

    def parse_html_to_doc(self, html_content: str, file_name: str) -> Dict[str, Any]:
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            meta = self._parse_metadata(soup)
            holdings = self._parse_holdings_table(soup)
            cover_url = self._parse_book_cover(soup)

            source_info = self._build_source_info(file_name)

            valid_extensions = ('.jpg', '.jpeg', '.png', '.webp')
            is_valid_img = any(cover_url.lower().endswith(ext) for ext in valid_extensions)

            has_cover = bool(
                cover_url and
                "no-image" not in cover_url.lower() and
                is_valid_img
            )

            return {
                # SOURCE / TRACEABILITY
                **source_info,
                "source": "minio_raw_html",
                "source_file": file_name,
                "ingested_at": datetime.utcnow().isoformat(),

                # CORE METADATA (RAW)
                "title": meta["title"],
                "category_raw": meta["category_raw"],
                "authors_raw": meta["authors_raw"],
                "publisher_raw": meta["publisher_raw"],

                # DETAIL ATTRIBUTES
                "jenis_bahan": meta["jenis_bahan"],
                "judul_alternatif": meta["judul_alternatif"],
                "edisi": meta["edisi"],
                "pernyataan_seri": meta["pernyataan_seri"],
                "language": meta["language"],
                "deskripsi_fisik": meta["deskripsi_fisik"],
                "isbn": meta["isbn"],

                # ABSTRAK
                "abstrak": meta["abstrak"],
                "has_abstrak": not self.is_empty_abstrak(meta["abstrak"]),

                # COVER
                "cover_url": cover_url,
                "has_cover": has_cover,

                # HOLDINGS (RAW NESTED)
                "num_holdings": len(holdings),
                "holdings": holdings,
            }

        except Exception as e:
            print(f"[ERROR] Parsing gagal untuk {file_name}: {e}", flush=True)
            return {
                "source_id": file_name,
                "error": str(e),
                "source": "html_parse_failed",
                "ingested_at": datetime.utcnow().isoformat()
            }

    def process_single_key(self, key):
        try:
            html_str = self.client.get_html_content(self.source_bucket, key)
            return self.parse_html_to_doc(html_str, key)
        except Exception as e:
            print(f"[ERROR] Thread gagal untuk {key}: {e}", flush=True)
            return {
                "source_id": key,
                "error": str(e),
                "source": "thread_failed"
            }

    def run_etl(self, chunk_size: int = 5000, max_workers: int = 10):
        print(f"[*] Menjalankan run_etl untuk bucket: {self.source_bucket}", flush=True)

        current_dir = Path(__file__).resolve().parent
        cache_file = current_dir / "html_keys_cache.txt"

        all_keys = []

        # 1. Cek apakah file .txt sudah ada
        if cache_file.exists():
            print(f"[*] Menemukan cache di {cache_file}. Membaca daftar file...", flush=True)
            with open(cache_file, "r") as f:
                all_keys = [line.strip() for line in f if line.strip()]
            print(f"[*] Berhasil memuat {len(all_keys)} file dari cache.", flush=True)
        else:
            # 2. Jika tidak ada, baru panggil fungsi list_all_html_files yang lama
            all_keys = self.client.list_all_html_files(self.source_bucket, prefix="html/")

            # Simpan ke .txt biar aman buat running berikutnya
            if all_keys:
                print(f"[*] Menyimpan daftar ke {cache_file}...", flush=True)
                with open(cache_file, "w") as f:
                    for key in all_keys:
                        f.write(f"{key}\n")

        total_files = len(all_keys)

        if total_files == 0:
            print("[!] Tidak ada file untuk diproses.")
            return

        current_batch = []
        batch_count = 1

        print(f"[*] Memulai Multi-threaded ETL dengan {max_workers} workers...", flush=True)

        # 2. Gunakan ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Map task ke workers
            future_to_key = {executor.submit(self.process_single_key, key): key for key in all_keys}

            # Gunakan tqdm untuk memantau progres completion
            pbar = tqdm(as_completed(future_to_key), total=total_files, desc="Multi-threaded ETL", unit="file",
                        file=sys.stdout)

            for future in pbar:
                doc = future.result()
                current_batch.append(doc)

                # 3. Checkpoint: Upload jika batch penuh
                if len(current_batch) >= chunk_size:
                    file_name = f"jsonl/books_raw_part_{batch_count:03d}.jsonl"
                    self.client.upload_jsonl(self.target_bucket, current_batch, file_name)

                    # Update info di tqdm
                    pbar.set_postfix({"last_batch": batch_count})

                    current_batch = []
                    batch_count += 1

            # Upload sisa data yang tidak mencapai chunk_size di akhir
            if current_batch:
                file_name = f"jsonl/books_raw_part_{batch_count:03d}.jsonl"
                self.client.upload_jsonl(self.target_bucket, current_batch, file_name)

        print(f"\n[FINISH] ETL Selesai. Data tersimpan di bucket: {self.target_bucket}")


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    m_client = MinioClient(
        endpoint=get_env("MINIO_ENDPOINT"),
        access_key=get_env("MINIO_ACCESS_KEY"),
        secret_key=get_env("MINIO_SECRET_KEY")
    )

    bucket_name = get_env("MINIO_BUCKET_BRONZE")

    etl = BronzeBookETL(
        minio_client=m_client,
        source_bucket=bucket_name,
        target_bucket=bucket_name  # Simpan di bucket yang sama, tapi dengan file baru hasil transformasi
    )

    etl.run_etl(chunk_size=5000, max_workers=15)