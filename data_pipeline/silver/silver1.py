"""
data_pipeline/silver/silver1.py — LLM Enrichment Layer
───────────────────────────────────────────────────────
Membaca output silver.py, lalu memanggil Ollama (temperature=0) untuk
mengekstrak vibes, setting, dan characters dari abstract_clean.

Scope: semua buku yang punya abstract_clean valid (bukan hanya fiksi).

Input  : data_pipeline/silver/books_silver_part_*.jsonl
Output : data_pipeline/silver/books_silver_enriched_part_*.jsonl
"""

import os
import re
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv, find_dotenv
from langchain_ollama import ChatOllama

load_dotenv(find_dotenv())

# Windows default console codepage (cp1252) can't encode the arrow below; force UTF-8.
sys.stdout.reconfigure(encoding="utf-8")

SILVER_DIR = Path(__file__).resolve().parent

# Request fan-out ke Ollama — request berjalan paralel jadi server selalu punya antrian,
# tidak menunggu round-trip satu-per-satu seperti loop sekuensial.
MAX_WORKERS = 8


# ── LLM setup ─────────────────────────────────────────────────────────────────

def _build_llm():
    return ChatOllama(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        temperature=0,
        format="json",
    )


_SYSTEM_PROMPT = (
    "Kamu adalah sistem ekstraksi informasi. "
    "Balas HANYA dengan JSON valid, tanpa penjelasan tambahan. "
    'Format: {"vibes": [...], "setting": [...], "characters": [...]}\n'
    "- vibes: nuansa/tema cerita (romance, misteri, thriller, dll.) — maks 5 item\n"
    "- setting: latar tempat/dunia cerita (pedesaan, perkotaan, kerajaan, dll.) — maks 3 item\n"
    "- characters: nama tokoh utama yang disebut eksplisit — maks 5 item\n"
    "Jika tidak ada, kembalikan list kosong []."
)

_EMPTY = {"vibes": [], "setting": [], "characters": []}


def _extract_json(text: str) -> dict:
    """Coba parse JSON dari respons LLM. Fallback ke empty dict jika gagal."""
    text = text.strip()
    # Coba langsung
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Coba ekstrak blok JSON dari dalam teks
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def enrich_record(llm, abstract_clean: str) -> dict:
    """Panggil LLM untuk 1 abstrak. Kembalikan dict enrichment atau empty."""
    messages = [
        ("system", _SYSTEM_PROMPT),
        ("human", f"Sinopsis:\n{abstract_clean}"),
    ]
    try:
        response = llm.invoke(messages)
        raw = response.content if hasattr(response, "content") else str(response)
        parsed = _extract_json(raw)
        return {
            "vibes": parsed.get("vibes") or [],
            "setting": parsed.get("setting") or [],
            "characters": parsed.get("characters") or [],
        }
    except Exception as e:
        print(f"    [!] LLM error: {e}")
        return dict(_EMPTY)


# ── Core processing ───────────────────────────────────────────────────────────

def enrich_partition(llm, records: list[dict]) -> list[dict]:
    """Enrichment satu partisi via thread pool (map/reduce). Mutate in-place, kembalikan list yang sama."""
    eligible = [r for r in records if r.get("abstract_clean")]
    total = len(records)
    n_eligible = len(eligible)
    print(f"    [*] {n_eligible}/{total} records punya abstract valid → enrichment LLM ({MAX_WORKERS} worker paralel)", flush=True)

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_rec = {executor.submit(enrich_record, llm, rec["abstract_clean"]): rec for rec in eligible}
        for future in as_completed(future_to_rec):
            rec = future_to_rec[future]
            enrichment = future.result()
            rec["vibes"] = enrichment["vibes"]
            rec["setting"] = enrichment["setting"]
            rec["characters"] = enrichment["characters"]
            done += 1
            if done % 50 == 0 or done == n_eligible:
                print(f"    [*] Progress: {done}/{n_eligible}", flush=True)

    # Buku tanpa abstract_clean tetap masuk dengan field kosong
    no_abstract_ids = {r["book_id"] for r in records} - {r["book_id"] for r in eligible}
    for rec in records:
        if rec["book_id"] in no_abstract_ids:
            rec.setdefault("vibes", [])
            rec.setdefault("setting", [])
            rec.setdefault("characters", [])

    return records


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[*] Menginisialisasi LLM Ollama...")
    llm = _build_llm()
    # Warm-up: pastikan Ollama bisa menjawab sebelum memproses ribuan record
    try:
        llm.invoke([("human", 'Balas dengan: {"vibes":[],"setting":[],"characters":[]}')])
        print("[*] Ollama siap.")
    except Exception as e:
        print(f"[!] Ollama tidak bisa dihubungi: {e}")
        raise SystemExit(1)

    silver_files = sorted(SILVER_DIR.glob("books_silver_part_*.jsonl"))
    if not silver_files:
        print(f"[!] Tidak ada file books_silver_part_*.jsonl di {SILVER_DIR}.")
        raise SystemExit(0)

    print(f"[*] Ditemukan {len(silver_files)} partisi silver untuk dienrich.")

    for part_path in silver_files:
        enriched_path = SILVER_DIR / part_path.name.replace("books_silver_", "books_silver_enriched_")

        print(f"\n[*] Memproses: {part_path.name}")

        try:
            with open(part_path, encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]

            enriched = enrich_partition(llm, records)

            with open(enriched_path, "w", encoding="utf-8") as f:
                for rec in enriched:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            print(f"    [+] Tersimpan: {enriched_path}")

        except Exception as e:
            print(f"[!] Error pada {part_path.name}: {e}")

    print("\n[DONE] LLM enrichment selesai.")
