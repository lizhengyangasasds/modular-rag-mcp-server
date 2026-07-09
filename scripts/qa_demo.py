# -*- coding: utf-8 -*-
"""Standalone test: retrieve chunks, then call LLM to generate an answer with [n] citations."""
import asyncio
import io
import sys
from pathlib import Path

# UTF-8 stdout (Windows)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from src.core.settings import load_settings
from src.core.query_engine.query_processor import QueryProcessor
from src.core.query_engine.hybrid_search import create_hybrid_search
from src.core.query_engine.dense_retriever import create_dense_retriever
from src.core.query_engine.sparse_retriever import create_sparse_retriever
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.libs.embedding.embedding_factory import EmbeddingFactory
from src.libs.vector_store.vector_store_factory import VectorStoreFactory
from src.core.response.rag_response_builder import create_rag_response_builder
from src.observability.logger import get_logger

logger = get_logger(__name__)

COLLECTION = "knowledge_hub"
TOP_K = 5
QUERY = "什么是神经网络"


async def main():
    settings = load_settings("config/settings.yaml")
    print(f"[OK] Settings loaded")
    try:
        print(f"[*] LLM provider: {settings.llm.provider}")
        print(f"[*] LLM model: {settings.llm.model}")
    except Exception as e:
        print(f"[WARN] could not read LLM settings: {e}")
    print(f"[*] Collection: {COLLECTION}")
    print(f"[*] Query: {QUERY}\n")

    # Build hybrid search
    vector_store = VectorStoreFactory.create(settings, collection_name=COLLECTION)
    embedding_client = EmbeddingFactory.create(settings)
    dense_retriever = create_dense_retriever(
        settings=settings, embedding_client=embedding_client, vector_store=vector_store,
    )
    bm25_indexer = BM25Indexer(index_dir=f"data/db/bm25/{COLLECTION}")
    sparse_retriever = create_sparse_retriever(
        settings=settings, bm25_indexer=bm25_indexer, vector_store=vector_store,
    )
    sparse_retriever.default_collection = COLLECTION
    query_processor = QueryProcessor()
    hybrid_search = create_hybrid_search(
        settings=settings, query_processor=query_processor,
        dense_retriever=dense_retriever, sparse_retriever=sparse_retriever,
    )

    # Run retrieval
    print("=" * 60)
    print("STEP 1: Hybrid Search (Dense + Sparse + RRF)")
    print("=" * 60)
    loop = asyncio.get_event_loop()
    hybrid_result = await loop.run_in_executor(
        None, lambda: hybrid_search.search(
            query=QUERY, top_k=TOP_K, filters=None, return_details=False,
        )
    )
    results = hybrid_result if isinstance(hybrid_result, list) else hybrid_result.results
    print(f"Retrieved {len(results)} chunks\n")

    if not results:
        print("[FAIL] No results retrieved.")
        return

    # Print retrieved chunks briefly
    for i, r in enumerate(results, 1):
        text = (r.text or "").replace("\n", " ")
        print(f"[{i}] score={r.score:.4f} chunk_id={r.chunk_id}")
        print(f"    text: {text[:160]}...")
        print()

    # Run RAG generation
    print("=" * 60)
    print("STEP 2: LLM Generation (RAG)")
    print("=" * 60)
    rag_builder = create_rag_response_builder(settings)
    print(f"LLM client type: {type(rag_builder.llm).__name__}")
    print(f"LLM model attr: {getattr(rag_builder.llm, '_model', 'N/A')}")
    print(f"Calling LLM...\n")

    try:
        response = await loop.run_in_executor(
            None, lambda: rag_builder.build(query=QUERY, results=results)
        )
    except Exception as e:
        print(f"[FAIL] RAG build failed: {e}")
        logger.exception("RAG build failed")
        return

    print("=" * 60)
    print("GENERATED ANSWER (with [n] citations)")
    print("=" * 60)
    print(response.content)
    print("\n" + "=" * 60)
    print(f"is_empty={response.is_empty}  generated={response.metadata.get('generated')}")
    print(f"citations_count={len(response.citations)}")
    print(f"model={response.metadata.get('generation_model')}")
    print("=" * 60)

    if response.citations:
        print("\nCITATIONS:")
        for i, c in enumerate(response.citations, 1):
            print(f"  [{i}] source={getattr(c, 'source', '')}  page={getattr(c, 'page', '')}")


asyncio.run(main())
