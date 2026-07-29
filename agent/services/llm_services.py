"""
agent/services/llm_services.py — LLM Factory (Ollama + Groq)
─────────────────────────────────────────────────────────────
Mendukung dua provider:
  - ollama  : Llama 3.1 / Qwen 2.5 via Ollama di GPU REMOTE (lihat
    OLLAMA_BASE_URL di bawah — bukan instance lokal di laptop).
  - groq    : Llama 3.1 via Groq Cloud (LPU)

Provider dipilih via env var ACTIVE_LLM_PROVIDER (default: ollama). Model
(Llama ATAU Qwen, keduanya lewat provider "ollama" yang sama) dipilih via
env var OLLAMA_MODEL — `agent.tools` tidak tahu/peduli model mana yang
sedang aktif, get_llm() murni baca env var saat dipanggil.

OLLAMA_BASE_URL **wajib diisi secara eksplisit di .env** — TIDAK ADA
fallback default. Proyek ini menjalankan Ollama di GPU remote (lihat
docs/deployment.md), bukan di laptop developer; kalau base URL nggak
diisi dan kode diam-diam fallback ke `localhost:11434`, ada risiko nyata
permintaan tanpa sengaja kena Ollama LOKAL (kalau kebetulan ada yang
jalan di situ juga) alih-alih GPU remote yang dimaksud — silent wrong
resource, bukan error yang kelihatan. Mending gagal eksplisit di awal.

Dua varian LLM diekspos:
  - `llm`      : plain-text generation (responder, standard_rag).
  - `llm_json` : dipakai Reasoner. format dikunci ke JSON ('format=json' di
    Ollama / response_format json_object di Groq) + num_predict dibatasi.
    Ini menghilangkan retry akibat output non-JSON (yang sebelumnya bisa
    menggandakan latency satu langkah ReAct) dan membatasi token generation
    karena objek aksi reasoner selalu kecil.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv, find_dotenv

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from pydantic import SecretStr

logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())

# Default token cap untuk plain-text (responder ditarget 2-4 paragraf).
_DEFAULT_NUM_PREDICT = 700


def get_llm(
    provider_name: Optional[str] = None,
    *,
    json_mode: bool = False,
    num_predict: Optional[int] = None,
):
    """
    Factory function untuk menginisialisasi LLM secara dinamis.
    Hanya mendukung 'ollama' dan 'groq' untuk testing lokal.

    Args:
        json_mode   : kunci output ke JSON (grammar-constrained di Ollama,
                      response_format di Groq/OpenAI-compatible).
        num_predict : cap token output (latency ceiling). Default
                      _DEFAULT_NUM_PREDICT jika tidak diisi.
    """
    provider = (provider_name or os.getenv("ACTIVE_LLM_PROVIDER", "ollama")).lower()
    cap = num_predict or _DEFAULT_NUM_PREDICT

    if provider == "groq":
        logger.info("Memuat LLM: Groq Cloud (LPU Architecture)")
        raw_key = os.getenv("GROQ_API_KEY")
        if not raw_key:
            raise ValueError(
                "GROQ_API_KEY tidak ditemukan di environment. "
                "Set di .env atau gunakan ACTIVE_LLM_PROVIDER=ollama."
            )
        kwargs: dict = {"max_tokens": cap}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(
            api_key=SecretStr(raw_key),
            base_url="https://api.groq.com/openai/v1",
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            temperature=0,
            **kwargs,
        )

    else:
        # Ollama — GPU remote, lihat docstring modul. base_url TIDAK PERNAH
        # fallback ke alamat default: kalau OLLAMA_BASE_URL tidak diset,
        # gagal eksplisit di sini daripada diam-diam memakai Ollama lokal.
        base_url_str = os.getenv("OLLAMA_BASE_URL")
        if not base_url_str:
            raise ValueError(
                "OLLAMA_BASE_URL tidak ditemukan di environment. Set di .env "
                "ke alamat GPU remote (mis. http://localhost:11450 kalau "
                "lewat SSH tunnel) — sengaja TIDAK ada fallback default ke "
                "Ollama lokal supaya tidak diam-diam salah resource."
            )
        model_name = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        logger.info(
            "Memuat LLM: Ollama @ %s (model=%s, json_mode=%s, num_predict=%d)",
            base_url_str, model_name, json_mode, cap,
        )
        kwargs = {"num_predict": cap}
        if json_mode:
            kwargs["format"] = "json"
        return ChatOllama(
            base_url=base_url_str,
            model=model_name,
            temperature=0,
            keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
            **kwargs,
        )


# Lazy initialization — hanya dibuat saat pertama kali diakses
_llm_instance = None
_llm_json_instance = None


def get_llm_instance():
    """Lazy singleton untuk LLM plain-text (responder, standard_rag)."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = get_llm()
    return _llm_instance


def get_llm_json_instance():
    """Lazy singleton untuk LLM mode JSON (reasoner)."""
    global _llm_json_instance
    if _llm_json_instance is None:
        _llm_json_instance = get_llm(json_mode=True, num_predict=500)
    return _llm_json_instance


# Backward compat: `from agent.services.llm_services import llm`
# Menggunakan property-like module-level access via __getattr__
def __getattr__(name):
    if name == "llm":
        return get_llm_instance()
    if name == "llm_json":
        return get_llm_json_instance()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
