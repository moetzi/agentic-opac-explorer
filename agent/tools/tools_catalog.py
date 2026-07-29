"""
agent/tools/tools_catalog.py — Parametric Cypher Tool Catalog
─────────────────────────────────────────────────────────────────
Flat, declarative registry: every tool is a name -> {params, description,
cypher} entry. No Python wrapper functions, no dynamic query building —
just a parameter list and a static Cypher template using Neo4j's native
$param binding. Whatever runs this catalog is responsible for supplying
values for each name in "params" and executing "cypher" via the driver.

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

"vector_search" is the one entry with cypher=None: semantic search needs a
Python-side embedding step (SentenceTransformer encode) before any Cypher
runs, so it can't be a static params -> cypher template like the rest.
agent/nodes/tool_executor.py special-cases it (see VECTOR_TOOLS below)
instead of dispatching through execute_query(). It is excluded from the
SEED_TOOLS/MULTIHOP_TOOLS/CURATION_TOOLS slices, but Search-Space-Gated's
EXPAND_TOOLS and PURE_REACT_TOOLS both append "vector_search" explicitly — so
the reasoner (SSG expand phase / pure-ReAct / act-only) and the Planned planner
CAN choose it. Standard RAG calls VectorSearchTool.search() directly instead.

EXACT-MATCH-FIRST ORDERING (retrieval-precision fix)
────────────────────────────────────────────────────
Every `books_by_*` attribute lookup filters with `toLower(node.name) CONTAINS
toLower($param)` (substring, so "romance" also catches "romance komedi") and
truncates with `LIMIT 50` (raised from 15 so a follow-up filter still has
candidates to narrow). Without ordering, a queried value that is a SUBSTRING
of a much larger sibling node silently loses: e.g. setting "desa" (36 books)
CONTAINS-matches "pedesaan" (122 books) too, and an unordered `LIMIT 50` returns
arbitrary pedesaan books — crowding out every exact-"desa" hit (P@3 → 0 even
though the ground truth is correct; verified on eval Q40). Each lookup therefore
computes a per-book `_exact` score (how many of its matched nodes equal the query
value exactly) and `ORDER BY _exact DESC, b.book_id` BEFORE `LIMIT 50`, so exact
matches are surfaced first and truncation is deterministic. Exact >= substring
always, so this never regresses a query that already worked. DDC lookups keep
`STARTS WITH` (prefix is intentional there), and vector_search is unaffected.
"""

CYPHER_TOOLS = {

    # ═══════════════════════════════════════════════════════════════
    # 1. SINGLE-HOP: Pencarian langsung per node type
    # ═══════════════════════════════════════════════════════════════

    "books_by_category": {
        "params": ["category"],
        "description": "Find books belonging to a given category.",
        "cypher": """
        MATCH (b:Book)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_branch": {
        "params": ["branch"],
        "description": "Find books available at a given library branch.",
        "cypher": """
        MATCH (b:Book)-[:AVAILABLE_AT]->(br:Branch)
        WHERE replace(replace(toLower(br.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($branch), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(br.name), ' ', ''), '.', '') = replace(replace(toLower($branch), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_author": {
        "params": ["author"],
        "description": "Find books written by a given author.",
        "cypher": """
        MATCH (a:Author)-[:WROTE]->(b:Book)
        WHERE replace(replace(toLower(a.name), ' ', ''), '.', '')
              CONTAINS replace(replace(toLower($author), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(a.name), ' ', ''), '.', '')
                            = replace(replace(toLower($author), ' ', ''), '.', '')
                         THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_publisher": {
        "params": ["publisher"],
        "description": "Find books published by a given publisher.",
        "cypher": """
        MATCH (b:Book)-[:PUBLISHED_BY]->(p:Publisher)
        WHERE replace(replace(toLower(p.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($publisher), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(p.name), ' ', ''), '.', '') = replace(replace(toLower($publisher), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_vibe": {
        "params": ["vibe"],
        "description": "Find books with a given vibe/mood.",
        "cypher": """
        MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe)
        WHERE replace(replace(toLower(v.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($vibe), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(v.name), ' ', ''), '.', '') = replace(replace(toLower($vibe), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_setting": {
        "params": ["setting"],
        "description": "Find books set in a given setting/location.",
        "cypher": """
        MATCH (b:Book)-[:HAS_SETTING]->(s:Setting)
        WHERE replace(replace(toLower(s.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($setting), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(s.name), ' ', ''), '.', '') = replace(replace(toLower($setting), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_character": {
        "params": ["character"],
        "description": "Find books featuring a given character.",
        "cypher": """
        MATCH (b:Book)-[:FEATURES_CHARACTER]->(ch:Character)
        WHERE replace(replace(toLower(ch.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($character), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(ch.name), ' ', ''), '.', '') = replace(replace(toLower($character), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_ddc": {
        "params": ["ddc_prefix"],
        "description": "Find books under a given Dewey Decimal Classification prefix.",
        "cypher": """
        MATCH (b:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass)
        WHERE ddc.code STARTS WITH $ddc_prefix
        WITH b LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches,
            collect(DISTINCT {name: c.name}) AS categories
        """,
    },

    "books_by_language": {
        "params": ["language"],
        "description": "Find books written in a given language.",
        "cypher": """
        MATCH (b:Book)-[:WRITTEN_IN]->(l:Language)
        WHERE replace(replace(toLower(l.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($language), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(l.name), ' ', ''), '.', '') = replace(replace(toLower($language), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: c.name}) AS categories,
            collect(DISTINCT {name: br.name}) AS branches
        """,
    },

    "books_by_collection_type": {
        "params": ["collection_type"],
        "description": "Find books of a given collection type (e.g. Monograf).",
        "cypher": """
        MATCH (b:Book)-[:COLLECTION_TYPE]->(ct:CollectionType)
        WHERE replace(replace(toLower(ct.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($collection_type), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(ct.name), ' ', ''), '.', '') = replace(replace(toLower($collection_type), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: c.name}) AS categories,
            collect(DISTINCT {name: br.name}) AS branches
        """,
    },

    "books_by_publisher_city": {
        "params": ["city"],
        "description": "Find books whose publisher is located in a given city.",
        "cypher": """
        MATCH (b:Book)-[:PUBLISHED_BY]->(p:Publisher)-[:LOCATED_IN]->(city:City)
        WHERE replace(replace(toLower(city.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($city), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(city.name), ' ', ''), '.', '') = replace(replace(toLower($city), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches
        """,
    },

    # ═══════════════════════════════════════════════════════════════
    # 2. TWO-HOP INTERSECTION: Kombinasi 2 filter sekaligus
    # ═══════════════════════════════════════════════════════════════

    "books_by_vibe_and_setting": {
        "params": ["vibe", "setting"],
        "description": "Find books matching both a vibe and a setting.",
        "cypher": """
        MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
              (b)-[:HAS_SETTING]->(s:Setting)
        WHERE replace(replace(toLower(v.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($vibe), ' ', ''), '.', '')
          AND replace(replace(toLower(s.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($setting), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(v.name), ' ', ''), '.', '') = replace(replace(toLower($vibe), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(s.name), ' ', ''), '.', '') = replace(replace(toLower($setting), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_vibe_and_category": {
        "params": ["vibe", "category"],
        "description": "Find books matching both a vibe and a category.",
        "cypher": """
        MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
              (b)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(v.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($vibe), ' ', ''), '.', '')
          AND replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(v.name), ' ', ''), '.', '') = replace(replace(toLower($vibe), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_setting_and_category": {
        "params": ["setting", "category"],
        "description": "Find books matching both a setting and a category.",
        "cypher": """
        MATCH (b:Book)-[:HAS_SETTING]->(s:Setting),
              (b)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(s.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($setting), ' ', ''), '.', '')
          AND replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(s.name), ' ', ''), '.', '') = replace(replace(toLower($setting), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_author_and_vibe": {
        "params": ["author", "vibe"],
        "description": "Find books by a given author matching a given vibe.",
        "cypher": """
        MATCH (a:Author)-[:WROTE]->(b:Book),
              (b)-[:HAS_VIBE]->(v:Vibe)
        WHERE replace(replace(toLower(a.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($author), ' ', ''), '.', '')
          AND replace(replace(toLower(v.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($vibe), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(a.name), ' ', ''), '.', '') = replace(replace(toLower($author), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(v.name), ' ', ''), '.', '') = replace(replace(toLower($vibe), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_author_and_setting": {
        "params": ["author", "setting"],
        "description": "Find books by a given author matching a given setting.",
        "cypher": """
        MATCH (a:Author)-[:WROTE]->(b:Book),
              (b)-[:HAS_SETTING]->(s:Setting)
        WHERE replace(replace(toLower(a.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($author), ' ', ''), '.', '')
          AND replace(replace(toLower(s.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($setting), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(a.name), ' ', ''), '.', '') = replace(replace(toLower($author), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(s.name), ' ', ''), '.', '') = replace(replace(toLower($setting), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_author_and_category": {
        "params": ["author", "category"],
        "description": "Find books by a given author in a given category.",
        "cypher": """
        MATCH (a:Author)-[:WROTE]->(b:Book),
              (b)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(a.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($author), ' ', ''), '.', '')
          AND replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(a.name), ' ', ''), '.', '') = replace(replace(toLower($author), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a2:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a2.name}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches
        """,
    },

    "books_by_ddc_and_branch": {
        "params": ["ddc_prefix", "branch"],
        "description": "Find books under a DDC prefix available at a given branch.",
        "cypher": """
        MATCH (b:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass),
              (b)-[:AVAILABLE_AT]->(br:Branch)
        WHERE ddc.code STARTS WITH $ddc_prefix
          AND replace(replace(toLower(br.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($branch), ' ', ''), '.', '')
        WITH b, max(CASE WHEN replace(replace(toLower(br.name), ' ', ''), '.', '') = replace(replace(toLower($branch), ' ', ''), '.', '') THEN 1 ELSE 0 END) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br2:Branch)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: br2.name}) AS branches,
            collect(DISTINCT {name: c.name}) AS categories
        """,
    },

    "books_by_vibe_and_branch": {
        "params": ["vibe", "branch"],
        "description": "Find books matching a vibe AND available at a given branch (single seed query — use this instead of vector_search/books_by_vibe + filter_by_branch for 'buku [vibe] di [cabang]' queries, since a branch-blind seed pool predictably collapses to near-zero after filtering).",
        "cypher": """
        MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
              (b)-[:AVAILABLE_AT]->(br:Branch)
        WHERE replace(replace(toLower(v.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($vibe), ' ', ''), '.', '')
          AND replace(replace(toLower(br.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($branch), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(v.name), ' ', ''), '.', '') = replace(replace(toLower($vibe), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(br.name), ' ', ''), '.', '') = replace(replace(toLower($branch), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br2:Branch)
        OPTIONAL MATCH (b)-[:HAS_VIBE]->(v2:Vibe)
        OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: br2.name}) AS branches,
            collect(DISTINCT {name: v2.name}) AS vibes,
            collect(DISTINCT {name: s.name}) AS settings
        """,
    },

    "books_by_category_and_branch": {
        "params": ["category", "branch"],
        "description": "Find books matching a category AND available at a given branch (single seed query — same rationale as books_by_vibe_and_branch).",
        "cypher": """
        MATCH (b:Book)-[:BELONGS_TO]->(c:Category),
              (b)-[:AVAILABLE_AT]->(br:Branch)
        WHERE replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
          AND replace(replace(toLower(br.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($branch), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(br.name), ' ', ''), '.', '') = replace(replace(toLower($branch), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    "books_by_collection_type_and_category": {
        "params": ["collection_type", "category"],
        "description": "Find books of a given collection type in a given category.",
        "cypher": """
        MATCH (b:Book)-[:COLLECTION_TYPE]->(ct:CollectionType),
              (b)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(ct.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($collection_type), ' ', ''), '.', '')
          AND replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(ct.name), ' ', ''), '.', '') = replace(replace(toLower($collection_type), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches
        """,
    },

    # ═══════════════════════════════════════════════════════════════
    # 3. THREE-HOP: Triple intersection
    # ═══════════════════════════════════════════════════════════════

    "books_by_vibe_and_setting_and_category": {
        "params": ["vibe", "setting", "category"],
        "description": "Find books matching a vibe, setting, and category simultaneously.",
        "cypher": """
        MATCH (b:Book)-[:HAS_VIBE]->(v:Vibe),
              (b)-[:HAS_SETTING]->(s:Setting),
              (b)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(v.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($vibe), ' ', ''), '.', '')
          AND replace(replace(toLower(s.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($setting), ' ', ''), '.', '')
          AND replace(replace(toLower(c.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($category), ' ', ''), '.', '')
        WITH b, max((CASE WHEN replace(replace(toLower(v.name), ' ', ''), '.', '') = replace(replace(toLower($vibe), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(s.name), ' ', ''), '.', '') = replace(replace(toLower($setting), ' ', ''), '.', '') THEN 1 ELSE 0 END)
                  + (CASE WHEN replace(replace(toLower(c.name), ' ', ''), '.', '') = replace(replace(toLower($category), ' ', ''), '.', '') THEN 1 ELSE 0 END)) AS _exact
        ORDER BY _exact DESC, b.book_id
        LIMIT 50
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
    },

    # ═══════════════════════════════════════════════════════════════
    # 4. COLLABORATIVE: "Buku lain dengan X yang sama" (3-4 hop)
    # ═══════════════════════════════════════════════════════════════

    "books_sharing_vibe_with": {
        "params": ["title"],
        "description": "Find other books that share a vibe with a reference book title.",
        "cypher": """
        MATCH (b1:Book)-[:HAS_VIBE]->(v:Vibe)<-[:HAS_VIBE]-(b2:Book)
        WHERE replace(toLower(b1.title), ' ', '') CONTAINS replace(toLower($title), ' ', '')
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
    },

    "books_sharing_vibe_with_setting": {
        "params": ["title", "setting"],
        "description": "Find other books sharing a vibe with a reference title, filtered by setting.",
        "cypher": """
        MATCH (b1:Book)-[:HAS_VIBE]->(v:Vibe)<-[:HAS_VIBE]-(b2:Book)-[:HAS_SETTING]->(s:Setting)
        WHERE replace(toLower(b1.title), ' ', '') CONTAINS replace(toLower($title), ' ', '')
          AND replace(replace(toLower(s.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($setting), ' ', ''), '.', '')
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
    },

    "books_sharing_ddc_with": {
        "params": ["title"],
        "description": "Find other books with the same DDC classification as a reference title.",
        "cypher": """
        MATCH (b1:Book)-[:CLASSIFIED_AS]->(ddc:DDCClass)<-[:CLASSIFIED_AS]-(b2:Book)
        WHERE replace(toLower(b1.title), ' ', '') CONTAINS replace(toLower($title), ' ', '')
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
    },

    "categories_by_author": {
        "params": ["author"],
        "description": "List categories (with book counts) written by a given author.",
        "cypher": """
        MATCH (a:Author)-[:WROTE]->(b:Book)-[:BELONGS_TO]->(c:Category)
        WHERE replace(replace(toLower(a.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($author), ' ', ''), '.', '')
        RETURN DISTINCT c.name AS category, count(b) AS book_count
        ORDER BY book_count DESC
        LIMIT 20
        """,
    },

    # ═══════════════════════════════════════════════════════════════
    # 5. SIMILARITY (runtime KNN) & POOL MAINTENANCE
    # ═══════════════════════════════════════════════════════════════

    "search_similar_runtime": {
        "params": ["title", "raw_k", "min_score", "top_k"],
        "description": "Find books similar to a reference title via vector embedding KNN. Best entry point for generic 'buku mirip/serupa/setema dengan <Judul>' queries. Pass ONLY the reference `title`; raw_k/min_score/top_k are auto-filled.",
        "cypher": """
        MATCH (target:Book)
        WHERE replace(toLower(target.title), ' ', '') CONTAINS replace(toLower($title), ' ', '')
          AND target.embedding IS NOT NULL
        WITH target ORDER BY size(target.title) ASC LIMIT 1
        CALL db.index.vector.queryNodes('book_vector_index', $raw_k, target.embedding)
        YIELD node AS b, score
        WITH target, b, score
        WHERE b.book_id <> target.book_id
          AND score >= $min_score
          AND toLower(trim(b.title)) <> toLower(trim(target.title))
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
        OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        WITH b, score,
             collect(DISTINCT {name: a.name, role: coalesce(a.role, 'penulis')}) AS authors,
             collect(DISTINCT {name: br.name}) AS branches,
             collect(DISTINCT {name: v.name}) AS vibes,
             collect(DISTINCT {name: s.name}) AS settings,
             collect(DISTINCT {name: c.name}) AS categories
        RETURN
            properties(b) AS book,
            score,
            'runtime' AS source,
            authors, branches, vibes, settings, categories
        ORDER BY score DESC
        LIMIT $top_k
        """,
    },

    "filter_by_author": {
        "params": ["book_ids", "author"],
        "description": "Narrow a set of book IDs to those written by a given author. Use to add an AUTHOR constraint to a pool seeded by a non-author attribute when NO combined books_by_*_and_* tool covers that pair — e.g. character + author (books_by_character THEN filter_by_author), or DDC + author.",
        "cypher": """
        MATCH (a:Author)-[:WROTE]->(b:Book)
        WHERE b.book_id IN $book_ids
          AND replace(replace(toLower(a.name), ' ', ''), '.', '')
              CONTAINS replace(replace(toLower($author), ' ', ''), '.', '')
        RETURN properties(b) AS book,
               collect(DISTINCT {name: a.name, role: coalesce(a.role, 'penulis')}) AS authors
        """,
    },

    "filter_by_branch": {
        "params": ["book_ids", "branch"],
        "description": "Check which of a set of book IDs are available at a given branch.",
        "cypher": """
        MATCH (b:Book)-[:AVAILABLE_AT]->(br:Branch)
        WHERE b.book_id IN $book_ids AND replace(replace(toLower(br.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($branch), ' ', ''), '.', '')
        RETURN properties(b) AS book, collect(DISTINCT {name: br.name}) AS branches
        """,
    },

    "filter_by_collection_type": {
        "params": ["book_ids", "collection_type"],
        "description": "Check which of a set of book IDs have a given collection type.",
        "cypher": """
        MATCH (b:Book)-[:COLLECTION_TYPE]->(ct:CollectionType)
        WHERE b.book_id IN $book_ids AND replace(replace(toLower(ct.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($collection_type), ' ', ''), '.', '')
        RETURN properties(b) AS book, collect(DISTINCT {name: ct.name}) AS collection_types
        """,
    },

    "filter_by_language": {
        "params": ["book_ids", "language"],
        "description": "Check which of a set of book IDs are written in a given language.",
        "cypher": """
        MATCH (b:Book)-[:WRITTEN_IN]->(l:Language)
        WHERE b.book_id IN $book_ids AND replace(replace(toLower(l.name), ' ', ''), '.', '') CONTAINS replace(replace(toLower($language), ' ', ''), '.', '')
        RETURN properties(b) AS book, collect(DISTINCT {name: l.name}) AS languages
        """,
    },

    "enrich_books": {
        "params": ["book_ids"],
        "description": "Fetch full ontology relations (author, branch, vibe, setting, category) for given book IDs.",
        "cypher": """
        MATCH (b:Book) WHERE b.book_id IN $book_ids
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
        OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name, role: coalesce(a.role, 'penulis')}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches,
            collect(DISTINCT {name: v.name}) AS vibes,
            collect(DISTINCT {name: s.name}) AS settings,
            collect(DISTINCT {name: c.name}) AS categories
        """,
    },

    "books_by_title_or_category_fuzzy": {
        "params": ["keyword"],
        "description": "FALLBACK safety-net: fuzzy-match a keyword against the RELIABLE catalog fields — book title OR raw category — when synopsis-extracted attributes (vibe/setting/character) return a sparse pool. Not a planner-selectable menu tool; auto-triggered by the Planned workflow when structured retrieval on fragile attributes is too sparse (see agent/core/workflow_planned.py).",
        "cypher": """
        MATCH (b:Book)
        WHERE replace(toLower(b.title), ' ', '') CONTAINS replace(toLower($keyword), ' ', '')
           OR any(cn IN [(b)-[:BELONGS_TO]->(c:Category) | toLower(c.name)]
                  WHERE cn CONTAINS toLower($keyword))
        WITH b LIMIT 50
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
        OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c2:Category)
        RETURN
            properties(b) AS book,
            collect(DISTINCT {name: a.name, role: coalesce(a.role, 'penulis')}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches,
            collect(DISTINCT {name: v.name}) AS vibes,
            collect(DISTINCT {name: s.name}) AS settings,
            collect(DISTINCT {name: c2.name}) AS categories
        """,
    },

    "lookup_by_title": {
        "params": ["title", "top_k"],
        "description": "Look up a book by exact or partial title match.",
        "cypher": """
        MATCH (b:Book)
        WHERE toLower(trim(b.title)) = toLower(trim($title))
           OR replace(toLower(b.title), ' ', '') CONTAINS replace(toLower($title), ' ', '')
        WITH b,
             CASE WHEN toLower(trim(b.title)) = toLower(trim($title)) THEN 2.0
                  ELSE 1.0 END AS exact_bonus
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:AVAILABLE_AT]->(br:Branch)
        OPTIONAL MATCH (b)-[:HAS_VIBE]->(v:Vibe)
        OPTIONAL MATCH (b)-[:HAS_SETTING]->(s:Setting)
        OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
        RETURN
            properties(b) AS book,
            exact_bonus AS score,
            collect(DISTINCT {name: a.name, role: coalesce(a.role, 'penulis')}) AS authors,
            collect(DISTINCT {name: br.name}) AS branches,
            collect(DISTINCT {name: v.name}) AS vibes,
            collect(DISTINCT {name: s.name}) AS settings,
            collect(DISTINCT {name: c.name}) AS categories
        ORDER BY score DESC, book.title
        LIMIT $top_k
        """,
    },

    "titles_to_ids": {
        "params": ["titles"],
        "description": "Resolve a list of book titles to their book_id values.",
        "cypher": """
        UNWIND $titles AS t
        MATCH (b:Book)
        WHERE replace(toLower(b.title), ' ', '') CONTAINS replace(toLower(t), ' ', '')
        WITH t, b ORDER BY size(b.title) ASC
        WITH t, collect(b)[0] AS hit
        WHERE hit IS NOT NULL
        RETURN hit.book_id AS book_id
        """,
    },

    # ═══════════════════════════════════════════════════════════════
    # 6. VECTOR SEARCH — semantic (E5) entry point. Not a Cypher template
    # ("cypher" is None) — agent/nodes/tool_executor.py special-cases this
    # name and calls VectorSearchTool.search() instead of execute_query().
    # Absent from the SEED/MULTIHOP/CURATION slices, but EXPAND_TOOLS &
    # PURE_REACT_TOOLS append it explicitly, so the Search-Space-Gated reasoner
    # (expand phase) and the Planned planner can both select it.
    # ═══════════════════════════════════════════════════════════════

    "vector_search": {
        "params": ["query"],
        "description": "Semantic search over book synopses/themes via embedding similarity (E5 + Neo4j vector index). Best for vague/thematic queries (vibe, mood, 'mirip buku X').",
        "cypher": None,
    },
}


# ═══════════════════════════════════════════════════════════════
# REGISTRY SLICES — the Search-Space-Gated workflow (agent/core/workflow.py)
# exposes a different subset of CYPHER_TOOLS to the reasoner depending on PHASE:
# the full retrieval menu in "expand", then shrink-only tools in "curate".
# ═══════════════════════════════════════════════════════════════

# Single-hop lookups — part of the full retrieval menu (EXPAND_TOOLS) the
# reasoner can pick from to SEED the pool in the expand phase.
SEED_TOOLS = [
    "books_by_category", "books_by_branch", "books_by_author", "books_by_publisher",
    "books_by_vibe", "books_by_setting", "books_by_character", "books_by_ddc",
    "books_by_language", "books_by_collection_type", "books_by_publisher_city",
    "lookup_by_title",
]

# 2/3-hop intersections — also part of the expand-phase retrieval menu, so a
# multi-attribute query can seed the pool with ONE precise composite tool
# instead of a broad seed followed by filters.
MULTIHOP_TOOLS = [
    "books_by_vibe_and_setting", "books_by_vibe_and_category", "books_by_setting_and_category",
    "books_by_author_and_vibe", "books_by_author_and_setting", "books_by_author_and_category",
    "books_by_ddc_and_branch", "books_by_vibe_and_branch", "books_by_category_and_branch",
    "books_by_collection_type_and_category", "books_by_vibe_and_setting_and_category",
]

# Pool-narrowing filters + reporting tool — available throughout the
# curation loop regardless of route.
CURATION_TOOLS = [
    "filter_by_author", "filter_by_branch", "filter_by_collection_type",
    "filter_by_language", "categories_by_author",
]

# "Buku lain dengan X yang sama dengan buku Y" — reference-title-driven
# graph traversal (shared vibe / shared vibe+setting / shared DDC). These
# templates already existed in CYPHER_TOOLS but were never listed in any
# of the gating slices above, so no reasoner (Search-Space-Gated or pure ReAct)
# could ever select them — collaborative-filtering queries had no path
# but vector_search, which has no notion of "same DDC/vibe as book X" and
# reliably stalls into the reasoner's loop-guard (see docs/analisis.md
# Temuan 1 / Q22-Q24). Now part of EXPAND_TOOLS (SSG) and PURE_REACT_TOOLS.
COLLABORATIVE_TOOLS = [
    "books_sharing_vibe_with", "books_sharing_vibe_with_setting", "books_sharing_ddc_with",
]

# "buku yang MIRIP/SERUPA/SETEMA dengan <Judul>" — generic semantic similarity to
# a reference book via embedding-KNN (search_similar_runtime). Distinct from the
# COLLABORATIVE_TOOLS above, which need an EXPLICIT shared attribute ("vibe/DDC
# yang sama"). Kept in its OWN slice (not folded into COLLABORATIVE_TOOLS) so it
# reaches only PURE_REACT_TOOLS — the Planned/pure-ReAct/act-only action space —
# WITHOUT leaking into the Search-Space-Gated reasoner's EXPAND_TOOLS
# (agent/core/workflow.py builds that from SEED+MULTIHOP+COLLABORATIVE only, so
# adding this here leaves Search-Space-Gated untouched). Fixes runtime_similarity queries
# (Q25-27/Q95-97) that previously had no path to search_similar_runtime and fell
# to the too-broad books_sharing_vibe_with (see docs/analisis.md § 4 Temuan 3).
SIMILARITY_TOOLS = ["search_similar_runtime"]

# Tools whose result REPLACES the pool with the matching subset (narrow),
# rather than merging new info into it (search/expand semantics).
FILTER_TOOLS = {"filter_by_author", "filter_by_branch", "filter_by_collection_type", "filter_by_language"}

# Tools whose results aren't book records — never merged into the pool,
# surfaced via observation text only.
NON_BOOK_TOOLS = {"categories_by_author"}

# Tools whose execution bypasses execute_query() entirely (Python-side
# embedding step instead of a static Cypher template). Checked by
# agent/nodes/tool_executor.py before the generic CYPHER_TOOLS dispatch.
VECTOR_TOOLS = {"vector_search"}

# Flat, ungated action space for the pure full-autonomy ReAct ablation
# (agent/core/workflow_pure_react.py): every graph tool + vector_search,
# all available from step 1 — no route/phase gating, no front-door.
PURE_REACT_TOOLS = SEED_TOOLS + MULTIHOP_TOOLS + CURATION_TOOLS + COLLABORATIVE_TOOLS + SIMILARITY_TOOLS + ["vector_search"]


# Category headers used by build_specs_prompt() to group tools in the
# reasoner-facing listing. Order matters: roughly the order a query gets
# resolved (semantic entry -> single-attribute seed -> multi-attribute
# combo -> pool curation). A flat undifferentiated list of 20+ tools is a
# known failure mode for small-model tool selection (the bigger the list,
# the worse the accuracy) — grouping under labeled headers is the standard
# mitigation that doesn't require restricting *what's* selectable (no
# router/gating change), only *how* it's presented.
_SPEC_GROUPS = [
    ("SEMANTIC SEARCH", VECTOR_TOOLS),
    ("SEED LOOKUP — single attribute", set(SEED_TOOLS)),
    ("MULTI-ATTRIBUTE COMBO", set(MULTIHOP_TOOLS)),
    ("COLLABORATIVE — \"buku lain dengan vibe/DDC yang SAMA dengan buku X\", needs a reference title", set(COLLABORATIVE_TOOLS)),
    ("SIMILARITY — \"buku MIRIP/SERUPA/SETEMA dengan judul X\" (generic semantic KNN), needs a reference title", set(SIMILARITY_TOOLS)),
    ("POOL CURATION — use only once the pool has candidates", set(CURATION_TOOLS)),
]


def build_specs_prompt(tool_names: list[str]) -> str:
    """
    Render a reasoner-facing tool spec listing for the given subset of
    CYPHER_TOOLS, grouped under labeled headers (see _SPEC_GROUPS). Headers
    are only printed when 2+ groups are actually present in `tool_names` —
    a single-group subset (e.g. Search-Space-Gated's curate-phase CURATION_TOOLS
    alone) stays a plain flat list, since grouping a 4-item list adds noise
    without reducing any real selection burden.
    """
    tool_set = list(dict.fromkeys(tool_names))  # preserve order, dedupe
    remaining = set(tool_set)

    def render(name: str) -> str:
        spec = CYPHER_TOOLS[name]
        params_str = ", ".join(spec["params"])
        return f"- {name}({params_str}): {spec['description']}"

    groups: list[tuple[str, list[str]]] = []
    for label, members in _SPEC_GROUPS:
        names = [n for n in tool_set if n in members]
        if names:
            groups.append((label, names))
            remaining -= set(names)
    if remaining:
        # Anything not in a known group (shouldn't normally happen) — keep
        # in original relative order, surfaced under its own header.
        groups.append(("OTHER", [n for n in tool_set if n in remaining]))

    lines: list[str] = []
    show_headers = len(groups) > 1
    for label, names in groups:
        if show_headers:
            lines.append(f"[{label}]")
        for name in names:
            lines.append(render(name))
    lines.append("- finish: Stop the loop & proceed to the responder. No arguments (use the 'selected_titles' field).")
    return "\n".join(lines)
