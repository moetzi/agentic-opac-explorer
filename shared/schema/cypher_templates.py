"""
shared/schema/cypher_templates.py — Cypher Query Templates
───────────────────────────────────────────────────────────
Graph Schema (11 node types, 11 relationship types):
    (:Author)-[:WROTE {role}]->(:Book)-[:PUBLISHED_BY]->(:Publisher)-[:LOCATED_IN]->(:City)
                                    ↓
                               [:BELONGS_TO]->(:Category)
                               [:WRITTEN_IN]->(:Language)
                               [:AVAILABLE_AT]->(:Branch)
                               [:CLASSIFIED_AS]->(:DDCClass)
                               [:COLLECTION_TYPE]->(:CollectionType)
                               [:HAS_VIBE]->(:Vibe)
                               [:HAS_SETTING]->(:Setting)
                               [:FEATURES_CHARACTER]->(:Character)

Multi-hop Strategy:
  - 2-hop intersection: kombinasi 2 filter sekaligus (vibe+setting, author+category, dll.)
  - 3-hop: Buku → entitas → entitas (misal: Author → Book → Category)
  - Collaborative: Book → Vibe → Book (buku lain dengan vibe yang sama)

Supernode Awareness:
  Branch hanya ~11 node tapi ribuan relasi → SELALU filter terakhir.
"""

TEMPLATES = {

    # ═══════════════════════════════════════════════════════════════
    # 1. SINGLE-HOP: Pencarian langsung per node type
    # ═══════════════════════════════════════════════════════════════

    "books_by_category": """
    MATCH (b:Book)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(c.name) CONTAINS toLower($category)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    OPTIONAL MATCH (b)-[:CLASSIFIED_AS]->(ddc:DDCClass)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings,
        collect(DISTINCT {code: ddc.code, description: ddc.description}) AS ddc_classes
    """,

    "books_by_branch": """
    MATCH (b:Book)-[:AVAILABLE_AT]->(br:Branch)
    WHERE toLower(br.name) CONTAINS toLower($branch)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br2:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br2.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    "books_by_author": """
    MATCH (a:Author)-[:WROTE]->(b:Book)
    WHERE toLower(a.name) CONTAINS toLower($author)
    WITH b LIMIT 15
    OPTIONAL MATCH (a2:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a2.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    "books_by_publisher": """
    MATCH (b:Book)-[:PUBLISHED_BY]->(p:Publisher)
    WHERE toLower(p.name) CONTAINS toLower($publisher)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    "books_by_vibe": """
    MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe)
    WHERE toLower(v.name) CONTAINS toLower($vibe)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    "books_by_setting": """
    MATCH (b:Book)-[:HAS_SETTING]->(s:Setting)
    WHERE toLower(s.name) CONTAINS toLower($setting)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s2:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s2.name}) AS settings
    """,

    "books_by_character": """
    MATCH (b:Book)-[:FEATURES_CHARACTER]->(ch:Character)
    WHERE toLower(ch.name) CONTAINS toLower($character)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    # ── New: DDC, Language, City, CollectionType ────────────────────

    "books_by_ddc": """
    MATCH (b:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass)
    WHERE ddc.code STARTS WITH $ddc_prefix
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: c.name}) AS categories
    """,

    "books_by_language": """
    MATCH (b:Book)-[:WRITTEN_IN]->(l:Language)
    WHERE toLower(l.name) CONTAINS toLower($language)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: c.name}) AS categories,
        collect(DISTINCT {name: br.name}) AS branches
    """,

    "books_by_collection_type": """
    MATCH (b:Book)-[:COLLECTION_TYPE]->(ct:CollectionType)
    WHERE toLower(ct.name) CONTAINS toLower($collection_type)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: c.name}) AS categories,
        collect(DISTINCT {name: br.name}) AS branches
    """,

    "books_by_publisher_city": """
    MATCH (b:Book)-[:PUBLISHED_BY]->(p:Publisher)-[:LOCATED_IN]->(city:City)
    WHERE toLower(city.name) CONTAINS toLower($city)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches
    """,


    # ═══════════════════════════════════════════════════════════════
    # 2. TWO-HOP INTERSECTION: Kombinasi 2 filter sekaligus
    # ═══════════════════════════════════════════════════════════════

    "books_by_vibe_and_setting": """
    MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
          (b)-[:HAS_SETTING]->(s:Setting)
    WHERE toLower(v.name) CONTAINS toLower($vibe)
      AND toLower(s.name) CONTAINS toLower($setting)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s2:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s2.name}) AS settings
    """,

    "books_by_vibe_and_category": """
    MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
          (b)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(v.name) CONTAINS toLower($vibe)
      AND toLower(c.name) CONTAINS toLower($category)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    "books_by_setting_and_category": """
    MATCH (b:Book)-[:HAS_SETTING]->(s:Setting),
          (b)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(s.name) CONTAINS toLower($setting)
      AND toLower(c.name) CONTAINS toLower($category)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s2:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s2.name}) AS settings
    """,

    "books_by_author_and_vibe": """
    MATCH (a:Author)-[:WROTE]->(b:Book),
          (b)-[:HAS_VIBE]->(v:Vibe)
    WHERE toLower(a.name) CONTAINS toLower($author)
      AND toLower(v.name) CONTAINS toLower($vibe)
    WITH b LIMIT 15
    OPTIONAL MATCH (a2:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a2.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    "books_by_author_and_setting": """
    MATCH (a:Author)-[:WROTE]->(b:Book),
          (b)-[:HAS_SETTING]->(s:Setting)
    WHERE toLower(a.name) CONTAINS toLower($author)
      AND toLower(s.name) CONTAINS toLower($setting)
    WITH b LIMIT 15
    OPTIONAL MATCH (a2:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s2:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a2.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v.name}) AS vibes,
        collect(DISTINCT {name: s2.name}) AS settings
    """,

    "books_by_author_and_category": """
    MATCH (a:Author)-[:WROTE]->(b:Book),
          (b)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(a.name) CONTAINS toLower($author)
      AND toLower(c.name) CONTAINS toLower($category)
    WITH b LIMIT 15
    OPTIONAL MATCH (a2:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a2.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches
    """,

    "books_by_ddc_and_branch": """
    MATCH (b:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass),
          (b)-[:AVAILABLE_AT]->(br:Branch)
    WHERE ddc.code STARTS WITH $ddc_prefix
      AND toLower(br.name) CONTAINS toLower($branch)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br2:Branch)
    OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br2.name}) AS branches,
        collect(DISTINCT {name: c.name}) AS categories
    """,

    "books_by_collection_type_and_category": """
    MATCH (b:Book)-[:COLLECTION_TYPE]->(ct:CollectionType),
          (b)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(ct.name) CONTAINS toLower($collection_type)
      AND toLower(c.name) CONTAINS toLower($category)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches
    """,

    # ═══════════════════════════════════════════════════════════════
    # 3. THREE-HOP: Triple intersection
    # ═══════════════════════════════════════════════════════════════

    "books_by_vibe_and_setting_and_category": """
    MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
          (b)-[:HAS_SETTING]->(s:Setting),
          (b)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(v.name) CONTAINS toLower($vibe)
      AND toLower(s.name) CONTAINS toLower($setting)
      AND toLower(c.name) CONTAINS toLower($category)
    WITH b LIMIT 15
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
    OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b)-[:HAS_SETTING]->(s2:Setting)
    RETURN 
        properties(b) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s2.name}) AS settings
    """,


    # ═══════════════════════════════════════════════════════════════
    # 4. COLLABORATIVE: "Buku lain dengan X yang sama"
    #    via shared Vibe/Setting/Author patterns (3-4 hop)
    # ═══════════════════════════════════════════════════════════════

    # 3-hop: Book → HAS_VIBE → Vibe ← HAS_VIBE ← Book (same vibe neighbors)
    # "Buku lain dengan vibe yang sama seperti buku X"
    "books_sharing_vibe_with": """
    MATCH (b1:Book)-[:HAS_VIBE]->(v:Vibe)<-[:HAS_VIBE]-(b2:Book)
    WHERE toLower(b1.title) CONTAINS toLower($title)
      AND b1 <> b2
    WITH b2, collect(v.name) AS shared_vibes
    ORDER BY size(shared_vibes) DESC
    LIMIT 10
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b2)
    OPTIONAL MATCH (b2)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b2)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b2)-[:HAS_SETTING]->(s:Setting)
    RETURN 
        properties(b2) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s.name}) AS settings
    """,

    # 4-hop: Book → HAS_VIBE → Vibe ← HAS_VIBE ← Book → HAS_SETTING → Setting
    # "Buku dengan vibe sama seperti X tapi berlatar Y"
    "books_sharing_vibe_with_setting": """
    MATCH (b1:Book)-[:HAS_VIBE]->(v:Vibe)<-[:HAS_VIBE]-(b2:Book)-[:HAS_SETTING]->(s:Setting)
    WHERE toLower(b1.title) CONTAINS toLower($title)
      AND toLower(s.name) CONTAINS toLower($setting)
      AND b1 <> b2
    WITH b2, collect(DISTINCT v.name) AS shared_vibes
    ORDER BY size(shared_vibes) DESC
    LIMIT 10
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b2)
    OPTIONAL MATCH (b2)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b2)-[:HAS_VIBE]->(v2:Vibe)
    OPTIONAL MATCH (b2)-[:HAS_SETTING]->(s2:Setting)
    RETURN 
        properties(b2) AS book,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: v2.name}) AS vibes,
        collect(DISTINCT {name: s2.name}) AS settings
    """,

    # 3-hop: Book → CLASSIFIED_AS → DDCClass ← CLASSIFIED_AS ← Book
    # "Buku lain dengan klasifikasi DDC yang sama"
    "books_sharing_ddc_with": """
    MATCH (b1:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass)<-[:CLASSIFIED_AS]-(b2:Book)
    WHERE toLower(b1.title) CONTAINS toLower($title)
      AND b1 <> b2
    WITH b2, ddc
    LIMIT 10
    OPTIONAL MATCH (a:Author)-[:WROTE]->(b2)
    OPTIONAL MATCH (b2)-[:AVAILABLE_AT]->(br:Branch)
    OPTIONAL MATCH (b2)-[:BELONGS_TO]->(c:Category)
    RETURN 
        properties(b2) AS book,
        ddc.code AS shared_ddc,
        collect(DISTINCT {name: a.name}) AS authors,
        collect(DISTINCT {name: br.name}) AS branches,
        collect(DISTINCT {name: c.name}) AS categories
    """,

    # 3-hop: Author → WROTE → Book → BELONGS_TO → Category
    # "Kategori apa saja yang ditulis oleh penulis X"
    "categories_by_author": """
    MATCH (a:Author)-[:WROTE]->(b:Book)-[:BELONGS_TO]->(c:Category)
    WHERE toLower(a.name) CONTAINS toLower($author)
    RETURN DISTINCT c.name AS category, count(b) AS book_count
    ORDER BY book_count DESC
    LIMIT 20
    """,
}
