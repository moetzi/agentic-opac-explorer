"""
shared/schema/neo4j_schema.py — Graph Ontology for Jakarta Public Library OPAC
───────────────────────────────────────────────────────────────────────────────
Ontologi graf yang dibangun dari data katalog OPAC Perpustakaan DKI Jakarta.
Semua entitas berasal dari data asli OPAC (bibliografis + kepustakaan),
kecuali Vibe/Setting/Character yang diekstrak via LLM dari abstrak buku
manapun yang punya abstract_clean valid (bukan hanya fiksi).
"""

# Structured schema (dipakai pipeline & agent)
GRAPH_SCHEMA = {
    "nodes": {
        # ── Entitas Inti ──────────────────────────────────────────────
        "Book": [
            "book_id", "title", "isbn_13", "pub_year", "total_pages",
            "abstract_clean", "is_fiction", "cover_url", "ddc_class",
            "edisi", "language",
        ],
        # ── Entitas Bibliografis (dari OPAC) ─────────────────────────
        "Author": ["name"],
        "Publisher": ["name"],
        "Category": ["name"],
        "Language": ["name"],
        "City": ["name"],
        # ── Entitas Kepustakaan (dari Holdings/Call Number) ──────────
        "Branch": ["name", "address"],
        "DDCClass": ["code", "description"],
        "CollectionType": ["name"],
        # ── Entitas Derivatif (LLM-extracted, open-vocabulary) ───────
        "Vibe": ["name"],
        "Setting": ["name"],
        "Character": ["name"],
    },
    "relationships": [
        ("Author", "WROTE", "Book"),
        ("Book", "PUBLISHED_BY", "Publisher"),
        ("Publisher", "LOCATED_IN", "City"),
        ("Book", "BELONGS_TO", "Category"),
        ("Book", "WRITTEN_IN", "Language"),
        ("Book", "AVAILABLE_AT", "Branch"),
        ("Book", "CLASSIFIED_AS", "DDCClass"),
        ("Book", "COLLECTION_TYPE", "CollectionType"),
        ("Book", "HAS_VIBE", "Vibe"),
        ("Book", "HAS_SETTING", "Setting"),
        ("Book", "FEATURES_CHARACTER", "Character"),
    ]
}


def get_schema_text():
    """Representasi teks dari skema graf, dipakai oleh LLM agent untuk memahami struktur data."""
    return """
Nodes:
Book {book_id: STRING, title: STRING, isbn_13: STRING, pub_year: INTEGER, total_pages: INTEGER, abstract_clean: STRING, is_fiction: BOOLEAN, cover_url: STRING, ddc_class: STRING, edisi: STRING, language: STRING}
Author {name: STRING}
Publisher {name: STRING}
Category {name: STRING}
Language {name: STRING}
City {name: STRING}
Branch {name: STRING, address: STRING}
DDCClass {code: STRING, description: STRING}
CollectionType {name: STRING}
Vibe {name: STRING}
Setting {name: STRING}
Character {name: STRING}

Relationships:
(:Author)-[:WROTE {role: STRING}]->(:Book)
(:Book)-[:PUBLISHED_BY]->(:Publisher)
(:Publisher)-[:LOCATED_IN]->(:City)
(:Book)-[:BELONGS_TO]->(:Category)
(:Book)-[:WRITTEN_IN]->(:Language)
(:Book)-[:AVAILABLE_AT]->(:Branch)
(:Book)-[:CLASSIFIED_AS]->(:DDCClass)
(:Book)-[:COLLECTION_TYPE]->(:CollectionType)
(:Book)-[:HAS_VIBE]->(:Vibe)
(:Book)-[:HAS_SETTING]->(:Setting)
(:Book)-[:FEATURES_CHARACTER]->(:Character)
"""