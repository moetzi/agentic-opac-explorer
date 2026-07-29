"""
agent/services/database.py — Neo4j Driver & Query Executor
───────────────────────────────────────────────────────────
Koneksi ke Neo4j dengan lazy initialization dan proper cleanup.
"""

import os
import atexit
import logging
from typing import List, Dict, Any, LiteralString, cast
from dotenv import load_dotenv, find_dotenv
from neo4j import GraphDatabase, Query

logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())

# ── Configuration ─────────────────────────────────────────────────────────
_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_auth_env = os.getenv("NEO4J_AUTH", "neo4j/password")
# Fix: split hanya pada "/" pertama agar password yang mengandung "/" tetap aman
_user, _password = _auth_env.split("/", 1)

# ── Lazy Driver Initialization ────────────────────────────────────────────
_driver = None


def get_driver():
    """Lazy singleton untuk Neo4j driver. Tidak crash saat import."""
    global _driver
    if _driver is None:
        logger.info("Menginisialisasi Neo4j driver: %s", _uri)
        _driver = GraphDatabase.driver(
            _uri,
            auth=(_user, _password),
            max_connection_lifetime=3600,
            connection_timeout=30,
        )
        # Register cleanup saat program exit
        atexit.register(_close_driver)
    return _driver


def _close_driver():
    """Tutup driver saat program selesai."""
    global _driver
    if _driver is not None:
        logger.info("Menutup Neo4j driver.")
        _driver.close()
        _driver = None


def execute_query(query_template: str, parameters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Mengeksekusi query Cypher secara type-safe.
    Returns list kosong jika query gagal (error di-log).
    """
    params: Dict[str, Any] = parameters if parameters is not None else {}

    try:
        driver = get_driver()
        with driver.session() as session:
            cypher_query = Query(cast(LiteralString, query_template))
            result = session.run(cypher_query, dict(params))
            return [record.data() for record in result]
    except Exception as e:
        logger.error(f"Gagal mengeksekusi query Cypher: {e}")
        return []
