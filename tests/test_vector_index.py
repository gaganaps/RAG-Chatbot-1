"""Unit and integration test suite for dense embeddings and ChromaDB vector indexing."""

import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List

import numpy as np
import pytest

from src.config import DATA_PROCESSED_DIR
from src.retrieval.embeddings import EmbeddingEngine, get_embedding_engine
from src.retrieval.indexer import VectorIndexer
from src.retrieval.vector_store import ChromaVectorStore


@pytest.fixture(scope="module")
def embedding_engine() -> EmbeddingEngine:
    """Shared EmbeddingEngine fixture."""
    return get_embedding_engine()


@pytest.fixture
def temp_vector_store(embedding_engine: EmbeddingEngine) -> ChromaVectorStore:
    """Isolated ChromaVectorStore rooted in a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = ChromaVectorStore(
            persist_dir=tmp_dir,
            collection_name="test_collection",
            embedding_engine=embedding_engine,
        )
        yield store


def test_embedding_engine_dimension_and_normalization(embedding_engine: EmbeddingEngine):
    """Verify BGE-small embedding dimension (384) and L2-normalization."""
    query = "What is the expense ratio of HDFC Flexi Cap Fund?"
    vec = embedding_engine.embed_query(query)

    assert len(vec) == 384
    norm = np.linalg.norm(vec)
    assert pytest.approx(norm, abs=1e-4) == 1.0

    docs = [
        "HDFC Flexi Cap Fund TER is 0.74%.",
        "Exit load of 1% if redeemed within 1 year.",
    ]
    batch_vecs = embedding_engine.embed_documents(docs)
    assert len(batch_vecs) == 2
    for b_vec in batch_vecs:
        assert len(b_vec) == 384
        assert pytest.approx(np.linalg.norm(b_vec), abs=1e-4) == 1.0


def test_vector_store_initialization_and_empty_state(temp_vector_store: ChromaVectorStore):
    """Verify empty store initialization and metadata reporting."""
    assert temp_vector_store.count() == 0
    stats = temp_vector_store.get_collection_stats()

    assert stats["collection_name"] == "test_collection"
    assert stats["total_documents"] == 0
    assert stats["vector_dimension"] == 384
    assert stats["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert stats["scheme_distribution"] == {}


def test_vector_store_upsert_and_retrieval(temp_vector_store: ChromaVectorStore):
    """Verify upserting chunks and retrieving by chunk_id."""
    sample_chunks = [
        {
            "chunk_id": "test_chunk_1",
            "scheme_id": "scheme-alpha",
            "scheme_name": "Alpha Fund Growth",
            "amc": "Test AMC",
            "category": "Equity",
            "section": "expense_ratio",
            "source_url": "https://example.com/alpha",
            "last_scraped_date": "2026-11-15",
            "text": "[SCHEME]: Alpha Fund Growth\nTotal expense ratio is 0.50%.",
            "token_count": 30,
        },
        {
            "chunk_id": "test_chunk_2",
            "scheme_id": "scheme-beta",
            "scheme_name": "Beta Fund Growth",
            "amc": "Test AMC",
            "category": "Hybrid",
            "section": "exit_load",
            "source_url": "https://example.com/beta",
            "last_scraped_date": "2026-11-15",
            "text": "[SCHEME]: Beta Fund Growth\nExit load is nil after 30 days.",
            "token_count": 35,
        },
    ]

    count = temp_vector_store.upsert_chunks(sample_chunks)
    assert count == 2
    assert temp_vector_store.count() == 2

    # Retrieve by chunk_id
    record = temp_vector_store.get_chunk_by_id("test_chunk_1")
    assert record is not None
    assert record["chunk_id"] == "test_chunk_1"
    assert "0.50%" in record["text"]
    assert record["metadata"]["scheme_id"] == "scheme-alpha"
    assert record["metadata"]["section"] == "expense_ratio"

    non_existent = temp_vector_store.get_chunk_by_id("non_existent_id")
    assert non_existent is None


def test_idempotent_upsert(temp_vector_store: ChromaVectorStore):
    """Verify that re-upserting identical chunk_ids updates rather than duplicates."""
    chunk = {
        "chunk_id": "idempotent_chunk",
        "scheme_id": "scheme-alpha",
        "scheme_name": "Alpha Fund Growth",
        "amc": "Test AMC",
        "category": "Equity",
        "section": "nav",
        "source_url": "https://example.com/alpha",
        "last_scraped_date": "2026-11-15",
        "text": "[SCHEME]: Alpha Fund Growth\nNAV is 100.00",
        "token_count": 20,
    }

    temp_vector_store.upsert_chunks([chunk])
    assert temp_vector_store.count() == 1

    # Update text and re-upsert
    chunk_updated = dict(chunk)
    chunk_updated["text"] = "[SCHEME]: Alpha Fund Growth\nNAV updated to 105.50"
    temp_vector_store.upsert_chunks([chunk_updated])

    # Count must remain 1
    assert temp_vector_store.count() == 1
    rec = temp_vector_store.get_chunk_by_id("idempotent_chunk")
    assert "105.50" in rec["text"]


def test_metadata_filtering(temp_vector_store: ChromaVectorStore):
    """Verify metadata filtering strictly partitions search results."""
    chunks = [
        {
            "chunk_id": f"filter_alpha_{i}",
            "scheme_id": "alpha-scheme",
            "scheme_name": "Alpha Scheme",
            "amc": "Alpha AMC",
            "category": "Equity",
            "section": "portfolio",
            "source_url": "https://example.com/alpha",
            "last_scraped_date": "2026-11-15",
            "text": f"Alpha scheme top holdings and equity portfolio {i}",
            "token_count": 25,
        }
        for i in range(3)
    ] + [
        {
            "chunk_id": f"filter_beta_{i}",
            "scheme_id": "beta-scheme",
            "scheme_name": "Beta Scheme",
            "amc": "Beta AMC",
            "category": "Debt",
            "section": "portfolio",
            "source_url": "https://example.com/beta",
            "last_scraped_date": "2026-11-15",
            "text": f"Beta scheme corporate debt and sovereign bonds holdings {i}",
            "token_count": 25,
        }
        for i in range(3)
    ]

    temp_vector_store.upsert_chunks(chunks)
    assert temp_vector_store.count() == 6

    # Query with alpha filter
    alpha_results = temp_vector_store.similarity_search(
        query="holdings and portfolio allocation",
        k=5,
        filter_dict={"scheme_id": "alpha-scheme"},
    )
    assert len(alpha_results) == 3
    for r in alpha_results:
        assert r["metadata"]["scheme_id"] == "alpha-scheme"

    # Query with beta filter
    beta_results = temp_vector_store.similarity_search(
        query="holdings and portfolio allocation",
        k=5,
        filter_dict={"scheme_id": "beta-scheme"},
    )
    assert len(beta_results) == 3
    for r in beta_results:
        assert r["metadata"]["scheme_id"] == "beta-scheme"


def test_semantic_similarity_search_ranking(temp_vector_store: ChromaVectorStore):
    """Verify semantic search ranks semantically aligned content at top."""
    chunks = [
        {
            "chunk_id": "hdfc_flexi_exit_load",
            "scheme_id": "hdfc-flexi-cap",
            "scheme_name": "HDFC Flexi Cap Direct Plan Growth",
            "amc": "HDFC Mutual Fund",
            "category": "Equity",
            "section": "exit_load",
            "source_url": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
            "last_scraped_date": "2026-11-15",
            "text": "[SECTION]: Exit Load\nExit load of 1% if redeemed within 1 year from the date of allotment.",
            "token_count": 30,
        },
        {
            "chunk_id": "hdfc_flexi_expense_ratio",
            "scheme_id": "hdfc-flexi-cap",
            "scheme_name": "HDFC Flexi Cap Direct Plan Growth",
            "amc": "HDFC Mutual Fund",
            "category": "Equity",
            "section": "expense_ratio",
            "source_url": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
            "last_scraped_date": "2026-11-15",
            "text": "[SECTION]: Expense Ratio\nThe Total Expense Ratio (TER) is 0.74% inclusive of GST.",
            "token_count": 28,
        },
    ]

    temp_vector_store.upsert_chunks(chunks)

    # Search for redemption penalty / exit load
    results = temp_vector_store.similarity_search(
        query="What is the exit fee or redemption penalty for selling early?",
        k=2,
    )
    assert len(results) == 2
    assert results[0]["chunk_id"] == "hdfc_flexi_exit_load"
    assert results[0]["score"] > results[1]["score"]
    assert 0.0 <= results[0]["score"] <= 1.0


def test_persistence_across_instances(embedding_engine: EmbeddingEngine):
    """Verify ChromaDB data persists across distinct client instances on disk."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Instance 1: write
        store1 = ChromaVectorStore(
            persist_dir=tmp_dir,
            collection_name="persist_test",
            embedding_engine=embedding_engine,
        )
        chunk = {
            "chunk_id": "persisted_chunk_01",
            "scheme_id": "hdfc-silver",
            "scheme_name": "HDFC Silver ETF FoF",
            "amc": "HDFC Mutual Fund",
            "category": "Commodities",
            "section": "min_investment",
            "source_url": "https://example.com/silver",
            "last_scraped_date": "2026-11-15",
            "text": "Minimum SIP investment is Rs 100.",
            "token_count": 20,
        }
        store1.upsert_chunks([chunk])
        assert store1.count() == 1

        # Instance 2: read from same disk directory
        store2 = ChromaVectorStore(
            persist_dir=tmp_dir,
            collection_name="persist_test",
            embedding_engine=embedding_engine,
        )
        assert store2.count() == 1
        rec = store2.get_chunk_by_id("persisted_chunk_01")
        assert rec is not None
        assert rec["metadata"]["scheme_id"] == "hdfc-silver"


def test_real_corpus_indexing_and_scheme_coverage():
    """Verify that VectorIndexer indexes the actual 50 chunks from Phase 1 corpus."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_store = ChromaVectorStore(
            persist_dir=tmp_dir,
            collection_name="hdfc_test_full",
        )
        indexer = VectorIndexer(
            vector_store=test_store,
            processed_dir=DATA_PROCESSED_DIR,
        )

        summary = indexer.build_vector_index(force_reindex=True)
        assert summary["status"] == "SUCCESS"
        assert summary["chunks_upserted"] == 50
        assert summary["total_collection_count"] == 50
        assert summary["vector_dimension"] == 384

        expected_schemes = {
            "hdfc-flexi-cap",
            "hdfc-silver-etf-fof",
            "hdfc-balanced-advantage",
            "hdfc-large-and-mid-cap",
            "hdfc-manufacturing",
        }
        indexed_schemes = set(summary["scheme_distribution"].keys())
        assert indexed_schemes == expected_schemes
        for scheme_id, chunk_count in summary["scheme_distribution"].items():
            assert chunk_count >= 9, f"Scheme {scheme_id} has fewer than 9 chunks ({chunk_count})"
