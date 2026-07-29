"""
app_web/examples.py — canonical example queries surfaced by GET /api/examples.

(Moved here from the retired app/ Streamlit package so the web backend is
self-contained. The deprecated Streamlit UI keeps its own copy under
deprecated/streamlit/examples.py.)
"""

EXAMPLE_QUERIES: list[str] = [
    "Rekomendasikan buku romance berlatar pedesaan",
    "Buku misteri yang berlatar perkotaan",
    "Buku adventure berlatar sekolah",
    "Buku mirip dengan A Wrinkle In Time",
    "Buku romance yang tersedia di Perpustakaan Cikini",
    "Buku historical berlatar kerajaan",
    "Buku karya Blyton yang petualangan",
    "Buku fiksi Indonesia romance",
]
