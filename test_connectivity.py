"""
test_connectivity.py — Verifikasi koneksi ke semua service sebelum run workflow.
──────────────────────────────────────────────────────────────────────────────────
Jalankan ini dulu untuk memastikan Neo4j, Ollama/Groq, dan Embedding model siap.

  python test_connectivity.py
  python test_connectivity.py --llama-model llama3.1:8b --qwen-model qwen2.5:7b

Kalau ACTIVE_LLM_PROVIDER=ollama, Llama dan Qwen dites BERGANTIAN (satu
model di-load, dites, lalu di-unload dari VRAM sebelum model berikutnya
dimuat) — bukan dua-duanya numpuk sekaligus di VRAM GPU remote.
"""

import argparse
import os
import sys
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

PASS = "✅"
FAIL = "❌"
results = []


def check(name: str, fn):
    """Run a check function and report pass/fail."""
    try:
        detail = fn()
        results.append((PASS, name, detail))
        print(f"  {PASS} {name}: {detail}")
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  {FAIL} {name}: {e}")


def test_neo4j():
    from agent.services.database import execute_query
    rows = execute_query("RETURN 1 AS ok")
    if rows and rows[0].get("ok") == 1:
        return "Connected"
    raise RuntimeError("Query returned unexpected result")


def test_neo4j_data():
    from agent.services.database import execute_query
    rows = execute_query("MATCH (b:Book) RETURN count(b) AS cnt")
    cnt = rows[0]["cnt"] if rows else 0
    if cnt == 0:
        raise RuntimeError("Tidak ada node :Book di database. Sudah ingest data gold?")
    return f"{cnt} buku ditemukan"


def test_neo4j_vector_index():
    from agent.services.database import execute_query
    rows = execute_query("SHOW INDEXES YIELD name WHERE name = 'book_vector_index' RETURN name")
    if not rows:
        raise RuntimeError("Vector index 'book_vector_index' belum dibuat di Neo4j")
    return "Index exists"


def _ollama_base_url() -> str:
    """
    OLLAMA_BASE_URL wajib di-set eksplisit — TIDAK ADA fallback ke
    localhost:11434, selaras dengan agent/services/llm_services.py (lihat
    docstring di file itu: proyek ini jalan di GPU remote, bukan laptop).
    """
    base = os.getenv("OLLAMA_BASE_URL")
    if not base:
        raise RuntimeError(
            "OLLAMA_BASE_URL tidak di-set. Wajib diisi ke alamat GPU remote "
            "(mis. http://localhost:11450 lewat SSH tunnel) — tidak ada "
            "fallback default supaya tidak diam-diam kena Ollama lokal."
        )
    return base


def _unload_ollama_model(model_name: str, base_url: str) -> None:
    """
    Best-effort: evict `model_name` dari VRAM lewat request kosong + sebuah
    `keep_alive: 0` ke /api/generate (cara resmi Ollama buat unload
    immediate). Sengaja BUKAN `ollama stop` CLI — CLI itu pakai OLLAMA_HOST
    sendiri (default 127.0.0.1:11434), yang bisa beda dari OLLAMA_BASE_URL
    kalau GPU remote diakses lewat SSH tunnel ke port non-default. Salah
    target = diam-diam nggak ngapa-ngapain.
    """
    try:
        import requests
        requests.post(
            f"{base_url}/api/generate",
            json={"model": model_name, "keep_alive": 0},
            timeout=15,
        )
    except Exception as exc:
        print(f"     (unload '{model_name}' gagal, non-fatal: {exc})")


def test_ollama_model_available(model_name: str):
    import requests
    base = _ollama_base_url()
    resp = requests.get(f"{base}/api/tags", timeout=5)
    resp.raise_for_status()
    models = [m["name"] for m in resp.json().get("models", [])]
    if not any(model_name in m for m in models):
        raise RuntimeError(f"Model '{model_name}' tidak ditemukan di {base}. Models: {models}")
    return f"Model '{model_name}' tersedia di {base}"


def test_groq():
    provider = os.getenv("ACTIVE_LLM_PROVIDER", "ollama")
    if provider != "groq":
        return f"Skipped (provider={provider})"
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY tidak di-set")
    import requests
    resp = requests.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return f"API key valid, {len(resp.json().get('data', []))} models"


def test_embedding_model():
    model_name = os.getenv("EMBEDDING_MODEL", "LazarusNLP/all-indo-e5-small-v4")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    vec = model.encode("query: test")
    return f"Loaded, dim={len(vec)}"


def test_llm_invoke(model_name: str):
    """Override OLLAMA_MODEL sementara, panggil get_llm() FRESH (tidak lewat
    singleton llm/llm_json — get_llm() langsung selalu baca env saat itu)."""
    os.environ["OLLAMA_MODEL"] = model_name
    from agent.services.llm_services import get_llm
    llm_inst = get_llm()
    from langchain_core.messages import HumanMessage
    resp = llm_inst.invoke([HumanMessage(content="Jawab dengan satu kata: 1+1=")])
    content = getattr(resp, "content", "")
    if not content:
        raise RuntimeError("LLM returned empty response")
    return f"Response: '{content[:50]}'"


def main():
    parser = argparse.ArgumentParser(description="Connectivity preflight check")
    parser.add_argument(
        "--llama-model", default=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        help="Model Llama yang dites (default: OLLAMA_MODEL di .env, atau llama3.1:8b)",
    )
    parser.add_argument(
        "--qwen-model", default="qwen2.5:7b",
        help="Model Qwen yang dites (default: qwen2.5:7b)",
    )
    args = parser.parse_args()

    provider = os.getenv("ACTIVE_LLM_PROVIDER", "ollama")

    print("\n" + "=" * 60)
    print("  CONNECTIVITY TEST — Agentic GraphRAG")
    print("=" * 60)
    print(f"  Provider: {provider}")
    print(f"  Neo4j   : {os.getenv('NEO4J_URI', 'bolt://localhost:7687')}")
    if provider == "ollama":
        print(f"  Models  : Llama={args.llama_model} | Qwen={args.qwen_model} (dites bergantian)")
    print("-" * 60)

    check("Neo4j Connection", test_neo4j)
    check("Neo4j Data (Books)", test_neo4j_data)
    check("Neo4j Vector Index", test_neo4j_vector_index)
    check("Groq API", test_groq)
    check("Embedding Model", test_embedding_model)

    if provider != "ollama":
        print(f"  ⏭️  Ollama checks: Skipped (provider={provider})")
    else:
        # Llama dan Qwen dites BERGANTIAN — unload sebelum model berikutnya
        # dimuat, supaya VRAM GPU remote tidak menampung dua model sekaligus.
        check("Ollama Base URL", _ollama_base_url)
        base_url = os.getenv("OLLAMA_BASE_URL")

        for label, model_name in (("Llama", args.llama_model), ("Qwen", args.qwen_model)):
            check(f"Ollama Service ({label})", lambda m=model_name: test_ollama_model_available(m))
            check(f"LLM Invoke ({label})", lambda m=model_name: test_llm_invoke(m))
            if base_url:
                print(f"     unloading '{model_name}' dari VRAM sebelum model berikutnya...")
                _unload_ollama_model(model_name, base_url)

    print("\n" + "-" * 60)
    failed = [r for r in results if r[0] == FAIL]
    if failed:
        print(f"  {len(failed)} check(s) GAGAL. Perbaiki sebelum run workflow.")
        sys.exit(1)
    else:
        print(f"  Semua {len(results)} checks LULUS. Siap run: python test_agent.py")
        sys.exit(0)


if __name__ == "__main__":
    main()
