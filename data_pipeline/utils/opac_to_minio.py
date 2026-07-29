"""
OPAC -> MinIO Bronze Layer Crawler
=====================================
Target    : 166.710 buku (11.114 halaman x 15 buku)
Arsitektur: OPAC Server -> Thread Pool -> MinIO (stream langsung)
Estimasi  : ~2.3 jam (10 thread x 0.5s delay = ~20 req/s)

Keunggulan vs notebook lama:
  - Tidak ada GDrive / ZIP / file lokal
  - Resume otomatis — aman kalau laptop sleep atau proses dimatikan
  - Memory konstan — html_bytes dibuang setiap selesai upload
  - Progress disimpan ke crawler.log, bisa dipantau kapanpun

Instalasi:
    pip install requests minio beautifulsoup4 lxml

Jalankan:
    # Kumpulkan link dulu (sekali saja)
    python opac_to_minio.py --collect --start 1 --end 11114

    # Download & upload ke MinIO
    python opac_to_minio.py --download --links collected_links.txt

    # Atau sekaligus
    python opac_to_minio.py --collect --start 1 --end 11114 --download

    # Retry link yang gagal
    python opac_to_minio.py --download --links failed_links.txt

Pantau progress:
    tail -f crawler.log   (Linux/Mac)
    Get-Content crawler.log -Wait   (PowerShell)
"""

import io
import os
import time
import logging
import threading
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from minio import Minio
from minio.error import S3Error
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# ══════════════════════════════════════════════════════
# KONFIGURASI — sesuaikan sebelum dijalankan
# ══════════════════════════════════════════════════════

# — OPAC —
BASE_URL    = "https://kios-perpustakaan.jakarta.go.id"
CATALOG_URL = f"{BASE_URL}/catalogue?page="
HEADERS     = {
    "User-Agent": "RisetMahasiswaSI_ITS/1.0 (5026221045@student.its.ac.id)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# — MinIO —
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET   = os.getenv("MINIO_BUCKET_BRONZE") # Menggunakan bronze-opac
MINIO_PREFIX   = "html"
MINIO_SECURE   = os.getenv("MINIO_SECURE") == "True"

# — Concurrency —
DOWNLOAD_WORKERS = 10   # thread download+upload paralel
LINK_WORKERS     = 10   # thread kumpul link katalog

# — Throttling —
REQUEST_DELAY = 3.0     # detik jeda per thread (10 thread = ~20 req/s total)

# — File state —
LINK_FILE   = "collected_links.txt"
FAILED_FILE = "failed_links.txt"
LOG_FILE    = "crawler.log"

# ══════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
# GRACEFUL SHUTDOWN
# Kalau Ctrl+C ditekan, simpan failed_links dulu baru berhenti
# ══════════════════════════════════════════════════════

_shutdown = threading.Event()

def _handle_sigint(sig, frame):
    if not _shutdown.is_set():
        log.warning("\nCtrl+C diterima — menyelesaikan request aktif, lalu berhenti...")
        _shutdown.set()

signal.signal(signal.SIGINT, _handle_sigint)

# ══════════════════════════════════════════════════════
# SESSION (thread-local — satu session per thread,
# menghindari race condition pada connection pool)
# ══════════════════════════════════════════════════════

_local = threading.local()

def get_session() -> requests.Session:
    if not hasattr(_local, "session"):
        retry = Retry(
            total=3,
            status_forcelist=[500, 502, 503, 504],
            backoff_factor=1,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=DOWNLOAD_WORKERS,
            pool_maxsize=DOWNLOAD_WORKERS,
        )
        s = requests.Session()
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(HEADERS)
        _local.session = s
    return _local.session

# ══════════════════════════════════════════════════════
# MINIO (singleton — thread-safe bawaan library)
# ══════════════════════════════════════════════════════

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS,
    secret_key=MINIO_SECRET,
    secure=MINIO_SECURE,
)

def ensure_bucket():
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
        log.info(f"Bucket '{MINIO_BUCKET}' dibuat.")

def already_in_minio(object_name: str) -> bool:
    """
    Cek keberadaan objek via stat_object — O(1), tidak perlu listdir.
    Jauh lebih cepat dari os.listdir yang tadi jadi bottleneck di GDrive.
    """
    try:
        minio_client.stat_object(MINIO_BUCKET, object_name)
        return True
    except S3Error as e:
        if e.code == "NoSuchKey":
            return False
        raise

# ══════════════════════════════════════════════════════
# LINK COLLECTOR
# ══════════════════════════════════════════════════════

def fetch_page_links(page_num: int) -> list[str]:
    """Ambil semua link /catalogue/detail/ dari satu halaman katalog."""
    if _shutdown.is_set():
        return []

    url     = f"{CATALOG_URL}{page_num}"
    session = get_session()
    time.sleep(REQUEST_DELAY)

    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            log.warning(f"Halaman {page_num}: HTTP {resp.status_code}, dilewati.")
            return []
        soup  = BeautifulSoup(resp.text, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/catalogue/detail/" in href:
                full = href if href.startswith("http") else f"{BASE_URL}{href}"
                links.append(full)
        return links
    except Exception as e:
        log.debug(f"Halaman {page_num} error: {e}")
        return []


def collect_links(start_page: int, end_page: int, output_file: str) -> list[str]:
    """
    Kumpulkan semua link dari rentang halaman katalog secara paralel.
    Hasil langsung disimpan ke file — aman kalau proses dihentikan di tengah jalan.
    """
    pages     = list(range(start_page, end_page + 1))
    all_links = []
    done      = 0

    log.info(f"Mengumpulkan link halaman {start_page}-{end_page} ({len(pages)} halaman, {LINK_WORKERS} thread)...")

    with ThreadPoolExecutor(max_workers=LINK_WORKERS) as ex:
        futures = {ex.submit(fetch_page_links, p): p for p in pages}
        for fut in as_completed(futures):
            all_links.extend(fut.result())
            done += 1
            if done % 500 == 0 or done == len(pages):
                log.info(f"  Halaman: {done}/{len(pages)} | Link terkumpul: {len(all_links)}")
            if _shutdown.is_set():
                break

    unique = list(set(all_links))
    save_links(unique, output_file)
    log.info(f"Total link unik: {len(unique)} -> disimpan ke {output_file}")
    return unique

# ══════════════════════════════════════════════════════
# DOWNLOADER + UPLOADER
# ══════════════════════════════════════════════════════

def process_book(url: str) -> tuple[str, bool, str]:
    """
    Download satu halaman buku dari OPAC lalu stream langsung ke MinIO.

    Tidak ada tulis ke disk — html_bytes hidup hanya selama satu request cycle,
    setelah put_object selesai langsung di-GC Python. Memory konstan.

    Returns: (url, success, reason)
    """
    if _shutdown.is_set():
        return url, False, "shutdown"

    book_id     = url.rstrip("/").split("/")[-1]
    object_name = f"{MINIO_PREFIX}/{book_id}.html"

    # Resume: skip kalau sudah ada di MinIO
    try:
        if already_in_minio(object_name):
            return url, True, "skip"
    except Exception:
        pass  # stat gagal -> tetap coba download

    time.sleep(REQUEST_DELAY)
    session = get_session()

    try:
        resp = session.get(url, timeout=60)

        if resp.status_code == 429:
            log.warning(f"429 rate limited [{book_id}] — akan di-retry putaran berikut")
            time.sleep(5)
            return url, False, "rate_limited"

        if resp.status_code != 200:
            return url, False, f"http_{resp.status_code}"

        # Stream ke MinIO — tidak menyentuh disk sama sekali
        html_bytes = resp.content
        minio_client.put_object(
            bucket_name  = MINIO_BUCKET,
            object_name  = object_name,
            data         = io.BytesIO(html_bytes),
            length       = len(html_bytes),
            content_type = "text/html; charset=utf-8",
            metadata     = {
                "x-amz-meta-source-url":  url,
                "x-amz-meta-crawled-at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "x-amz-meta-book-id":     book_id,
            },
        )
        return url, True, "ok"

    except requests.Timeout:
        return url, False, "timeout"
    except requests.RequestException as e:
        return url, False, f"network: {e}"
    except S3Error as e:
        log.error(f"MinIO error [{book_id}]: {e}")
        return url, False, f"minio: {e}"
    except Exception as e:
        return url, False, f"error: {e}"


def run_downloader(links: list[str], max_rounds: int = 3):
    """
    Loop utama dengan retry otomatis.
    Setiap putaran hanya memproses link yang belum berhasil.
    Kalau laptop sleep di tengah jalan dan proses mati:
      -> jalankan lagi dengan --links collected_links.txt
      -> yang sudah ada di MinIO akan di-skip otomatis via stat_object
    """
    ensure_bucket()

    queue   = list(set(links))
    total   = len(queue)
    t_start = time.time()

    log.info("=" * 60)
    log.info(f"Target   : {total} buku")
    log.info(f"Thread   : {DOWNLOAD_WORKERS} | Delay: {REQUEST_DELAY}s | ~{DOWNLOAD_WORKERS / REQUEST_DELAY:.0f} req/s")
    log.info(f"Estimasi : ~{total / (DOWNLOAD_WORKERS / REQUEST_DELAY) / 3600:.1f} jam")
    log.info(f"Resume   : jalankan ulang dengan file yang sama, yang sudah ada di MinIO di-skip")
    log.info(f"MinIO    : {MINIO_BUCKET}/{MINIO_PREFIX}/{{book_id}}.html")
    log.info("=" * 60)

    for round_num in range(1, max_rounds + 1):
        if not queue or _shutdown.is_set():
            break

        log.info(f"\n[Putaran {round_num}/{max_rounds}] {len(queue)} URL dalam antrian...")

        success_n = 0
        skip_n    = 0
        failed_q  = []
        r_start   = time.time()

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
            futures = {ex.submit(process_book, url): url for url in queue}

            for i, fut in enumerate(as_completed(futures), 1):
                if _shutdown.is_set():
                    break

                url, ok, reason = fut.result()

                if ok:
                    if reason == "skip":
                        skip_n += 1
                    else:
                        success_n += 1
                else:
                    failed_q.append(url)

                # Progress report setiap 200 item
                if i % 200 == 0 or i == len(queue):
                    elapsed   = time.time() - r_start
                    rate      = i / elapsed if elapsed > 0 else 0
                    eta_sec   = (len(queue) - i) / rate if rate > 0 else 0
                    pct       = (success_n + skip_n) / total * 100
                    log.info(
                        f"  [{i:>6}/{len(queue)}] "
                        f"baru={success_n} skip={skip_n} gagal={len(failed_q)} "
                        f"| {rate:.1f} req/s | ETA {eta_sec/60:.0f} mnt "
                        f"| total {pct:.1f}%"
                    )

        round_elapsed = time.time() - r_start
        log.info(
            f"Putaran {round_num} selesai dalam {round_elapsed/60:.1f} mnt — "
            f"baru={success_n}, skip={skip_n}, gagal={len(failed_q)}"
        )

        if _shutdown.is_set():
            log.info("Shutdown diminta — menyimpan sisa antrian ke failed_links.txt...")
            failed_q = list(queue)  # simpan semua yang belum diproses
            break

        if not failed_q:
            log.info("Semua URL berhasil!")
            break

        # Jika 100% gagal, server mungkin down — berhenti daripada spam
        if len(failed_q) == len(queue):
            log.warning("Semua URL gagal. Server mungkin tidak merespons. Berhenti.")
            break

        queue = failed_q

        if round_num < max_rounds:
            cooldown = 15 * round_num
            log.info(f"Cooling down {cooldown}s sebelum putaran berikutnya...")
            time.sleep(cooldown)

    # Simpan yang masih gagal — bisa di-retry nanti dengan --links failed_links.txt
    if failed_q:
        save_links(failed_q, FAILED_FILE)
        log.warning(f"{len(failed_q)} URL masih gagal -> disimpan ke {FAILED_FILE}")

    total_elapsed = time.time() - t_start
    done          = total - len(failed_q) if failed_q else total
    log.info(
        f"\n{'='*60}\n"
        f"SELESAI: {done}/{total} ({done/total*100:.1f}%) "
        f"dalam {total_elapsed/3600:.2f} jam\n"
        f"{'='*60}"
    )

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def save_links(links: list[str], filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(links) + "\n")
    log.info(f"{len(links)} link disimpan ke {filepath}")


def load_links(filepath: str) -> list[str]:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="OPAC -> MinIO Bronze Layer Crawler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python opac_to_minio.py --collect --start 1 --end 11114
  python opac_to_minio.py --download --links collected_links.txt
  python opac_to_minio.py --collect --start 1 --end 11114 --download
  python opac_to_minio.py --download --links failed_links.txt --rounds 5

Kalau proses berhenti di tengah (laptop sleep, Ctrl+C, dll):
  -> Jalankan ulang dengan perintah yang sama
  -> Yang sudah ada di MinIO otomatis di-skip
        """
    )
    parser.add_argument("--collect",  action="store_true", help="Kumpulkan link dari halaman katalog")
    parser.add_argument("--download", action="store_true", help="Download HTML & upload ke MinIO")
    parser.add_argument("--start",    type=int, default=1,         help="Halaman awal (default: 1)")
    parser.add_argument("--end",      type=int, default=11114,     help="Halaman akhir (default: 11114)")
    parser.add_argument("--links",    type=str, default=LINK_FILE, help=f"File link (default: {LINK_FILE})")
    parser.add_argument("--rounds",   type=int, default=3,         help="Maks putaran retry (default: 3)")
    args = parser.parse_args()

    if not args.collect and not args.download:
        parser.print_help()
        exit(0)

    links = []

    if args.collect:
        links = collect_links(args.start, args.end, args.links)

    if args.download:
        if not links:
            links = load_links(args.links)
        if not links:
            log.error(f"Tidak ada link. Pastikan '{args.links}' ada atau jalankan --collect dulu.")
            exit(1)
        run_downloader(links, max_rounds=args.rounds)
