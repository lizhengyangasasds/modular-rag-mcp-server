#!/usr/bin/env python
"""Re-run evaluation and save JSON with strict UTF-8 (no double encoding)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Ensure all stdout/stderr is UTF-8 to prevent GBK issues
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_eval():
    """Re-run evaluation and write clean JSON to logs/eval_report_clean.json."""
    from src.core.settings import load_settings
    from src.libs.evaluator.custom_evaluator import CustomEvaluator
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory
    from src.libs.embedding.embedding_factory import EmbeddingFactory
    from src.core.query_engine.query_processor import QueryProcessor
    from src.core.query_engine.hybrid_search import create_hybrid_search
    from src.core.query_engine.dense_retriever import create_dense_retriever
    from src.core.query_engine.sparse_retriever import create_sparse_retriever
    from src.ingestion.storage.bm25_indexer import BM25Indexer
    from src.observability.evaluation.eval_runner import EvalRunner

    settings = load_settings()
    collection = "knowledge_hub"

    vector_store = VectorStoreFactory.create(settings, collection_name=collection)
    embedding_client = EmbeddingFactory.create(settings)
    dense_retriever = create_dense_retriever(
        settings=settings,
        embedding_client=embedding_client,
        vector_store=vector_store,
    )
    bm25_indexer = BM25Indexer(index_dir=f"data/db/bm25/{collection}")
    sparse_retriever = create_sparse_retriever(
        settings=settings,
        bm25_indexer=bm25_indexer,
        vector_store=vector_store,
    )
    sparse_retriever.default_collection = collection

    query_processor = QueryProcessor()
    hybrid_search = create_hybrid_search(
        settings=settings,
        query_processor=query_processor,
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
    )

    evaluator = CustomEvaluator(settings=settings, metrics=["hit_rate", "mrr"])
    runner = EvalRunner(
        settings=settings,
        hybrid_search=hybrid_search,
        evaluator=evaluator,
    )

    test_set = "tests/fixtures/golden_test_set_v3.json"
    report = runner.run(test_set_path=test_set, top_k=10, collection=collection)
    return report


def main():
    report = run_eval()

    # Write clean UTF-8 JSON (no double encoding)
    output_path = Path("logs/eval_report_clean.json")
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Also dump just the answers to a readable file
    answer_path = Path("logs/eval_answers_human_readable.txt")
    with open(answer_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("Modular RAG MCP Server — Decoded LLM Answers\n")
        f.write(f"Test set: tests/fixtures/golden_test_set_v3.json | Top-K: 10\n")
        f.write("=" * 80 + "\n\n")

        for i, qr in enumerate(report.query_results, 1):
            f.write(f"[Query {i}] {qr.query}\n")
            f.write(f"  Hit Rate={qr.metrics.get('hit_rate', 0):.4f}  ")
            f.write(f"MRR={qr.metrics.get('mrr', 0):.4f}  ")
            f.write(f"Elapsed={qr.elapsed_ms:.0f}ms\n")
            f.write(f"  Retrieved chunks ({len(qr.retrieved_chunk_ids)}):\n")
            for cid in qr.retrieved_chunk_ids:
                f.write(f"    - {cid}\n")
            answer = (qr.generated_answer or "").strip()
            f.write(f"  Generated answer ({len(answer)} chars):\n")
            f.write(f"  {'-' * 76}\n")
            # Indent the answer for readability
            for line in answer.split("\n"):
                f.write(f"    {line}\n")
            f.write(f"  {'-' * 76}\n\n")

    print(f"OK - Wrote clean JSON: {output_path}")
    print(f"OK - Wrote human-readable answers: {answer_path}")


if __name__ == "__main__":
    main()
