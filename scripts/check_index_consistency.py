#!/usr/bin/env python
"""Check ChromaDB and BM25 index consistency."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.libs.vector_store.chroma_store import ChromaStore
from src.core.settings import load_settings
from src.ingestion.storage.bm25_indexer import BM25Indexer


def main():
    settings = load_settings()

    # 1. ChromaDB count
    store = ChromaStore(
        settings=settings,
        collection_name="knowledge_hub",
        persist_directory=str(Path("data/db/chroma")),
    )
    stats = store.get_collection_stats()
    chroma_count = stats.get("count", "?")
    print(f"ChromaDB chunk count: {chroma_count}")

    # 2. BM25 index stats
    indexer = BM25Indexer(index_dir="data/db/bm25/knowledge_hub")
    stats = indexer.get_stats()
    print(f"BM25 stats: {stats}")

    # 3. Test overlap - check if golden_test_set_v3 chunk IDs exist in ChromaDB
    golden_path = Path("tests/fixtures/golden_test_set_v3.json")
    if golden_path.exists():
        import json
        with open(golden_path, encoding="utf-8") as f:
            data = json.load(f)

        all_expected = set()
        for tc in data.get("test_cases", []):
            all_expected.update(tc.get("expected_chunk_ids", []))

        # Sample first 20
        sample_ids = list(all_expected)[:20]
        results = store.get_by_ids(ids=sample_ids)

        if results and results.get("ids"):
            found = set(results["ids"])
            missing = [i for i in sample_ids if i not in found]
            overlap = len(found) / len(sample_ids) * 100
            print(f"\nGolden test set v3 overlap check (first 20):")
            print(f"  Found: {len(found)}/{len(sample_ids)} ({overlap:.1f}%)")
            if missing:
                print(f"  Missing: {missing[:5]}")
            else:
                print(f"  All found!")
        else:
            print("\nGolden test set v3 overlap check: NO chunks found!")
            print("  → Chunk ID prefix mismatch detected!")
    else:
        print("golden_test_set_v3.json not found")

    # 4. Sample ChromaDB chunk IDs
    print("\nSample ChromaDB chunk IDs (first 5):")
    # Query for 5 random IDs using a dummy embedding
    dummy_embedding = [0.0] * 1536  # assuming 1536-dim embeddings
    query_result = store.collection.query(
        query_embeddings=[dummy_embedding],
        n_results=5,
    )
    sample_ids = query_result["ids"][0] if query_result.get("ids") else []
    for cid in sample_ids:
        print(f"  {cid}")


if __name__ == "__main__":
    main()
