"""
retriever.py — Semantic Search over SHL Catalog
================================================
Used by the agent (Step 5) to find relevant assessments.
This file goes in the agent/ folder.

USAGE (from agent code):
    from retriever import Retriever
    r = Retriever()
    results = r.search("hiring a Java developer", top_k=5)
    # returns list of assessment dicts with similarity scores
"""

import json
import pickle
import numpy as np
from pathlib import Path

DATA_DIR   = Path(__file__).parent.parent / "data"
INDEX_PATH = DATA_DIR / "faiss_index.bin"
PKL_PATH   = DATA_DIR / "retriever.pkl"

_instance = None   # module-level singleton so we only load once


class Retriever:
    """
    Wraps FAISS index + SentenceTransformer for semantic search.
    Loads lazily on first use; subsequent calls reuse the loaded model.
    """

    def __init__(self):
        import faiss
        from sentence_transformers import SentenceTransformer

        # Load the catalog + metadata bundle
        with open(PKL_PATH, "rb") as f:
            bundle = pickle.load(f)

        self.catalog    = bundle["catalog"]
        self.model_name = bundle["model_name"]
        self.model      = SentenceTransformer(self.model_name)
        self.index      = faiss.read_index(str(INDEX_PATH))

        print(f"[Retriever] Loaded {len(self.catalog)} assessments, model={self.model_name}")

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Semantic search over the catalog.

        Args:
            query:  Natural language query, e.g. "Java developer mid-level"
            top_k:  Number of results to return (max 10 per assignment spec)

        Returns:
            List of assessment dicts sorted by relevance, each with added
            'similarity_score' field (0.0 – 1.0, higher = more relevant).
        """
        # Embed and normalize query
        q_vec = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        # Search
        scores, ids = self.index.search(q_vec, min(top_k, len(self.catalog)))

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0:   # FAISS returns -1 for empty slots
                continue
            item = dict(self.catalog[idx])
            item["similarity_score"] = float(score)
            # Remove internal fields the agent doesn't need to pass to LLM
            item.pop("search_text", None)
            item.pop("index_id", None)
            results.append(item)

        return results

    def get_by_name(self, name: str) -> dict | None:
        """Exact name lookup — used for comparison queries."""
        name_lower = name.lower().strip()
        for item in self.catalog:
            if item.get("name", "").lower().strip() == name_lower:
                result = dict(item)
                result.pop("search_text", None)
                result.pop("index_id", None)
                return result
        return None

    def get_all(self) -> list[dict]:
        """Return entire catalog — used for building context window."""
        return [
            {k: v for k, v in item.items() if k not in ("search_text", "index_id")}
            for item in self.catalog
        ]


def get_retriever() -> Retriever:
    """Return the singleton Retriever instance (loads once per process)."""
    global _instance
    if _instance is None:
        _instance = Retriever()
    return _instance
