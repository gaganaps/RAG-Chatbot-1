"""Vector storage, lexical BM25 indexing, and hybrid retrieval module."""

from typing import Any

from src.retrieval.bm25_indexer import BM25Indexer, tokenize_finance
from src.retrieval.embeddings import EmbeddingEngine, get_embedding_engine
from src.retrieval.hybrid_retriever import HybridRetriever, RetrievalResult, SchemeEntityResolver
from src.retrieval.vector_store import ChromaVectorStore

__all__ = [
    "EmbeddingEngine",
    "get_embedding_engine",
    "ChromaVectorStore",
    "VectorIndexer",
    "BM25Indexer",
    "tokenize_finance",
    "HybridRetriever",
    "RetrievalResult",
    "SchemeEntityResolver",
]


def __getattr__(name: str) -> Any:
    """Lazy import for modules like VectorIndexer to avoid circular or early runtime import warnings."""
    if name == "VectorIndexer":
        from src.retrieval.indexer import VectorIndexer
        return VectorIndexer
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
