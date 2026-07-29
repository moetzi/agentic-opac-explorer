import os
import json
from pathlib import Path
from neo4j import GraphDatabase
from dotenv import find_dotenv, load_dotenv

# Cari .env dari root
load_dotenv(find_dotenv())

GRAPH_DIR = Path(__file__).resolve().parent.parent / "gold" / "graph"


# --- KLIEN NEO4J ---
class Neo4jIngestor:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        auth_env = os.getenv("NEO4J_AUTH", "neo4j/password")
        user, password = auth_env.split("/")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def run_query(self, query, parameters=None, message="Executing query..."):
        with self.driver.session() as session:
            session.run(query, parameters)
            print(f"    [+] {message}")

    def drop_all(self):
        print("\n[*] Menghapus seluruh graph yang ada...")
        self.run_query("MATCH (n) DETACH DELETE n", message="Graph lama telah dihapus.")

    def setup_schema(self):
        print("\n[*] Menyiapkan Schema dan Constraints...")
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (b:Book) REQUIRE b.book_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (br:Branch) REQUIRE br.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Publisher) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ddc:DDCClass) REQUIRE ddc.code IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Language) REQUIRE l.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:CollectionType) REQUIRE ct.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (v:Vibe) REQUIRE v.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Setting) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ch:Character) REQUIRE ch.name IS UNIQUE",
        ]
        for c in constraints:
            self.run_query(c, message=f"Constraint aktif: {c.split('FOR')[1].split('REQUIRE')[0].strip()}")

        vector_index = """
        CREATE VECTOR INDEX book_vector_index IF NOT EXISTS
        FOR (m:Book) ON (m.embedding)
        OPTIONS {indexConfig: {
         `vector.dimensions`: 384,
         `vector.similarity_function`: 'cosine'
        }}
        """
        self.run_query(vector_index, message="Vector Index siap (Dimensi: 384)")

    def ingest_data_from_local(self, graph_dir: Path):
        """Membaca graph/*.json dari folder gold lokal dan memasukkannya secara BATCHING ke Neo4j"""

        tasks = [
            {
                "file": "nodes_book.json",
                "label": "Books",
                "query": """
                    UNWIND $batch AS value
                    MERGE (b:Book {book_id: value.book_id})
                    SET b.title = value.title,
                        b.isbn_13 = value.isbn_13,
                        b.pub_year = value.pub_year,
                        b.total_pages = value.total_pages,
                        b.is_fiction = value.is_fiction,
                        b.abstract_clean = value.abstract_clean,
                        b.ddc_class = value.ddc_class,
                        b.edisi = value.edisi,
                        b.language = value.language,
                        b.cover_url = value.cover_url,
                        b.embedding = value.embedding
                """
            },
            {
                "file": "rels_written.json",
                "label": "Authors & WROTE rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (a:Author {name: value.author_name})
                    WITH a, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (a)-[:WROTE {role: value.role}]->(b)
                """
            },
            {
                "file": "rels_category.json",
                "label": "Categories & BELONGS_TO rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (c:Category {name: value.category_name})
                    WITH c, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:BELONGS_TO]->(c)
                """
            },
            {
                "file": "rels_published.json",
                "label": "Publishers & PUBLISHED_BY rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (p:Publisher {name: value.publisher_name})
                    WITH p, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:PUBLISHED_BY]->(p)
                    WITH p, value
                    FOREACH (_ IN CASE WHEN value.city IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (city:City {name: value.city})
                        MERGE (p)-[:LOCATED_IN]->(city)
                    )
                """
            },
            {
                "file": "rels_available.json",
                "label": "Branches & AVAILABLE_AT rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (br:Branch {name: value.branch_name})
                    SET br.address = value.address
                    WITH br, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:AVAILABLE_AT]->(br)
                """
            },
            {
                "file": "nodes_ddc.json",
                "label": "DDCClass.description backfill",
                "query": """
                    UNWIND $batch AS value
                    MERGE (ddc:DDCClass {code: value.code})
                    SET ddc.description = value.description
                """
            },
            {
                "file": "rels_ddc.json",
                "label": "DDCClass & CLASSIFIED_AS rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (ddc:DDCClass {code: value.ddc_code})
                    WITH ddc, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:CLASSIFIED_AS]->(ddc)
                """
            },
            {
                "file": "rels_language.json",
                "label": "Language & WRITTEN_IN rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (l:Language {name: value.language})
                    WITH l, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:WRITTEN_IN]->(l)
                """
            },
            {
                "file": "rels_collection_type.json",
                "label": "CollectionType & COLLECTION_TYPE rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (ct:CollectionType {name: value.collection_type})
                    WITH ct, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:COLLECTION_TYPE]->(ct)
                """
            },
            {
                "file": "rels_vibe.json",
                "label": "Vibes & HAS_VIBE rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (v:Vibe {name: value.vibe_name})
                    WITH v, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:HAS_VIBE]->(v)
                """
            },
            {
                "file": "rels_setting.json",
                "label": "Settings & HAS_SETTING rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (s:Setting {name: value.setting_name})
                    WITH s, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:HAS_SETTING]->(s)
                """
            },
            {
                "file": "rels_character.json",
                "label": "Characters & FEATURES_CHARACTER rels",
                "query": """
                    UNWIND $batch AS value
                    MERGE (ch:Character {name: value.character_name})
                    WITH ch, value MATCH (b:Book {book_id: value.book_id})
                    MERGE (b)-[:FEATURES_CHARACTER]->(ch)
                """
            },
        ]

        # --- OPTIMASI RAM NEO4J: BATCH SIZE ---
        # Memotong ribuan data menjadi potongan kecil agar Heap Memory Neo4j tidak crash
        BATCH_SIZE = 2000

        print(f"\n[*] Memulai Ingestion Data dari {graph_dir} ke Neo4j...")
        for task in tasks:
            file_path = graph_dir / task["file"]

            if not file_path.exists():
                print(f"\n[!] Melewati {task['file']} karena file tidak ditemukan.")
                continue

            with open(file_path, encoding="utf-8") as f:
                data_list = json.load(f)

            if data_list:
                total_records = len(data_list)
                print(f"\n[*] Memproses {task['label']} ({total_records} records)...")

                # Looping untuk memotong data menjadi chunk (ukuran sesuai BATCH_SIZE)
                for i in range(0, total_records, BATCH_SIZE):
                    chunk = data_list[i : i + BATCH_SIZE]

                    self.run_query(
                        task["query"],
                        parameters={"batch": chunk},
                        message=f"Tersimpan baris {i} hingga {i + len(chunk)}"
                    )
            else:
                print(f"\n[!] Melewati {task['file']} karena kosong.")

if __name__ == "__main__":
    ingestor = Neo4jIngestor()

    try:
        ingestor.drop_all()
        ingestor.setup_schema()
        ingestor.ingest_data_from_local(GRAPH_DIR)
        print("\n[SUCCESS] Pipeline Ingestion Selesai! GraphRAG siap digunakan.")
    except Exception as e:
        print(f"\n[!] Pipeline Terhenti: {e}")
    finally:
        ingestor.close()
