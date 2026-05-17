"""
Step 3 — Build Vector Search Index
====================================
Reads shl_catalog.json and creates a FAISS semantic search index.
This allows the agent to find relevant assessments from natural language
queries like "hiring a Java developer with stakeholder communication skills".

OUTPUT:
  ../data/faiss_index.bin          → the FAISS vector index
  ../data/catalog_indexed.json     → catalog with index positions preserved

HOW TO RUN:
  cd shl-assessment-recommender/embeddings
  pip install sentence-transformers faiss-cpu numpy
  python build_index.py
"""

import json
import pickle
import numpy as np
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────

DATA_DIR        = Path("../data")
INPUT_JSON      = DATA_DIR / "shl_catalog.json"
OUTPUT_INDEX    = DATA_DIR / "faiss_index.bin"
OUTPUT_CATALOG  = DATA_DIR / "catalog_indexed.json"
OUTPUT_PKL      = DATA_DIR / "retriever.pkl"   # bundles index + catalog together

# The embedding model — free, runs locally, no API key needed
# all-MiniLM-L6-v2 is fast (80ms/query) and good enough for this task
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


# ── TEXT BUILDER ──────────────────────────────────────────────────────────────

def build_search_text(assessment: dict) -> str:
    """
    Combine all useful fields into one string for embedding.
    The richer this text is, the better the semantic search works.

    Strategy:
    - Name gets repeated 3x (boosts exact name match weight)
    - Description is the main content
    - Test type names give category context
    - Job levels help match seniority queries
    - Languages help match language-specific queries
    """
    parts = []

    # Name repeated for emphasis
    name = assessment.get("name", "").strip()
    if name:
        parts.append(f"{name}. {name}. {name}.")

    # Description (most informative field)
    desc = assessment.get("description", "").strip()
    if desc:
        parts.append(desc)

    # Test type
    type_names = assessment.get("test_type_names", [])
    if type_names:
        parts.append("Test type: " + ", ".join(type_names))

    # Job levels
    levels = assessment.get("job_levels", [])
    if levels:
        parts.append("Job levels: " + ", ".join(levels))

    # Duration
    duration = assessment.get("duration", "").strip()
    if duration:
        parts.append(f"Duration: {duration}")

    # Remote testing
    if assessment.get("remote_testing"):
        parts.append("Supports remote testing.")

    # Adaptive
    if assessment.get("adaptive_irt"):
        parts.append("Adaptive test (IRT).")

    return " ".join(parts)


# ── BUILD INDEX ───────────────────────────────────────────────────────────────

def build_index(catalog: list[dict]):
    """
    Embed all assessments and store in a FAISS flat index.
    Returns (index, embeddings, texts).
    """
    import faiss
    from sentence_transformers import SentenceTransformer

    print(f"\nLoading embedding model: {EMBEDDING_MODEL}")
    print("(First run downloads ~90MB — subsequent runs use cache)\n")
    model = SentenceTransformer(EMBEDDING_MODEL)

    # Build text for each assessment
    texts = [build_search_text(a) for a in catalog]

    print(f"Embedding {len(texts)} assessments...")
    print("Sample text for first assessment:")
    print(f"  {texts[0][:200]}...\n")

    # Encode — batch_size=32 is safe for most machines
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,   # normalize so cosine sim = dot product
    )

    print(f"\nEmbedding shape: {embeddings.shape}")
    dim = embeddings.shape[1]

    # FAISS flat index with inner product (= cosine similarity on normalized vecs)
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings.astype(np.float32))

    print(f"FAISS index built: {index.ntotal} vectors, dimension {dim}")
    return index, embeddings, texts, model


# ── SAVE ──────────────────────────────────────────────────────────────────────

def save_all(index, catalog, embeddings, texts, model):
    import faiss

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Save FAISS index
    faiss.write_index(index, str(OUTPUT_INDEX))
    print(f"\nSaved FAISS index  ->  {OUTPUT_INDEX}")

    # 2. Save catalog with index positions (so retriever can map id → assessment)
    catalog_indexed = []
    for i, a in enumerate(catalog):
        catalog_indexed.append({
            "index_id": i,
            "search_text": texts[i],
            **a
        })
    with open(OUTPUT_CATALOG, "w", encoding="utf-8") as f:
        json.dump(catalog_indexed, f, indent=2, ensure_ascii=False)
    print(f"Saved indexed catalog  ->  {OUTPUT_CATALOG}")

    # 3. Save everything in one pickle for easy loading by the agent
    retriever_bundle = {
        "model_name": EMBEDDING_MODEL,
        "catalog": catalog_indexed,
        "dim": embeddings.shape[1],
    }
    with open(OUTPUT_PKL, "wb") as f:
        pickle.dump(retriever_bundle, f)
    print(f"Saved retriever bundle ->  {OUTPUT_PKL}")


# ── TEST SEARCH ───────────────────────────────────────────────────────────────

def test_search(index, catalog, model):
    """
    Run a few test queries to verify the index works correctly.
    You should see relevant assessments for each query.
    """
    import faiss

    test_queries = [
        "hiring a Java developer",
        "personality assessment for manager",
        "numerical reasoning ability test",
        "sales representative customer service",
        "cognitive ability graduate entry level",
    ]

    print("\n" + "=" * 60)
    print("TEST SEARCH — verifying index quality")
    print("=" * 60)

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        print("-" * 40)

        # Embed the query
        q_vec = model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True
        ).astype(np.float32)

        # Search top 3
        scores, ids = index.search(q_vec, 3)

        for rank, (score, idx) in enumerate(zip(scores[0], ids[0]), 1):
            name = catalog[idx].get("name", "Unknown")
            types = ", ".join(catalog[idx].get("test_type_names", []))
            print(f"  {rank}. {name}  [{types}]  (score: {score:.3f})")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Step 3 -- Build Vector Search Index")
    print("=" * 60)

    # 1. Load catalog
    if not INPUT_JSON.exists():
        print(f"\nERROR: {INPUT_JSON} not found.")
        print("Make sure Step 2 has been run successfully first.")
        return

    with open(INPUT_JSON, encoding="utf-8") as f:
        catalog = json.load(f)

    print(f"\nLoaded {len(catalog)} assessments from {INPUT_JSON}")

    if len(catalog) == 0:
        print("ERROR: Catalog is empty. Re-run Step 2.")
        return

    # 2. Build index
    index, embeddings, texts, model = build_index(catalog)

    # 3. Save
    save_all(index, catalog, embeddings, texts, model)

    # 4. Test
    test_search(index, catalog, model)

    print("\n" + "=" * 60)
    print("Step 3 complete!")
    print("Files created:")
    print(f"  {OUTPUT_INDEX}")
    print(f"  {OUTPUT_CATALOG}")
    print(f"  {OUTPUT_PKL}")
    print("\nReady for Step 4 (retriever + agent logic).")
    print("=" * 60)


if __name__ == "__main__":
    main()
