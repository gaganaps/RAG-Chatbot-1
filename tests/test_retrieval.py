"""Unit and integration test suite for BM25 lexical search and Hybrid Retrieval (RRF)."""

import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List

import pytest

from src.retrieval.bm25_indexer import BM25Indexer, tokenize_finance
from src.retrieval.hybrid_retriever import HybridRetriever, RetrievalResult, SchemeEntityResolver
from src.retrieval.vector_store import ChromaVectorStore


@pytest.fixture(scope="module")
def shared_bm25_indexer() -> BM25Indexer:
    """Shared BM25Indexer fixture loading the processed mutual fund corpus."""
    return BM25Indexer()


@pytest.fixture(scope="module")
def shared_vector_store() -> ChromaVectorStore:
    """Shared ChromaVectorStore fixture."""
    return ChromaVectorStore()


@pytest.fixture(scope="module")
def hybrid_retriever(shared_vector_store: ChromaVectorStore, shared_bm25_indexer: BM25Indexer) -> HybridRetriever:
    """Shared HybridRetriever fixture."""
    return HybridRetriever(
        vector_store=shared_vector_store,
        bm25_indexer=shared_bm25_indexer,
        rrf_k=60,
        dense_weight=1.0,
        sparse_weight=1.0,
    )


def test_tokenize_finance_acronyms_and_symbols():
    """Verify finance-aware tokenization preserves acronyms, currency signs, and percentages."""
    text = "What is the Total Expense Ratio (TER) of HDFC Flexi-Cap? Min SIP is ₹100, exit load 1%."
    tokens = tokenize_finance(text, remove_stopwords=True)

    # Financial acronyms
    assert "ter" in tokens
    assert "sip" in tokens

    # Currency expansion: ₹100 -> ₹100 and 100
    assert "₹100" in tokens
    assert "100" in tokens

    # Percentage expansion: 1% -> 1% and 1
    assert "1%" in tokens
    assert "1" in tokens

    # Hyphenated terms
    assert "flexi-cap" in tokens

    # English stopwords pruned
    assert "what" not in tokens
    assert "is" not in tokens
    assert "the" not in tokens
    assert "of" not in tokens


def test_bm25_indexer_build_and_persistence():
    """Verify BM25 index builds, persists to disk, and reloads without loss."""
    sample_corpus = [
        {
            "chunk_id": "test_ter_01",
            "scheme_id": "scheme-test",
            "scheme_name": "Test Scheme Direct",
            "amc": "Test AMC",
            "category": "Equity",
            "section": "expense_ratio",
            "source_url": "https://example.com/test",
            "last_scraped_date": "2026-11-15",
            "text": "[SCHEME]: Test Scheme\nTotal Expense Ratio (TER) is 0.65%.",
            "token_count": 25,
        },
        {
            "chunk_id": "test_exit_02",
            "scheme_id": "scheme-test",
            "scheme_name": "Test Scheme Direct",
            "amc": "Test AMC",
            "category": "Equity",
            "section": "exit_load",
            "source_url": "https://example.com/test",
            "last_scraped_date": "2026-11-15",
            "text": "[SCHEME]: Test Scheme\nExit load is 1% if redeemed within 1 year.",
            "token_count": 28,
        },
        {
            "chunk_id": "test_sip_03",
            "scheme_id": "scheme-test",
            "scheme_name": "Test Scheme Direct",
            "amc": "Test AMC",
            "category": "Equity",
            "section": "investment_limits",
            "source_url": "https://example.com/test",
            "last_scraped_date": "2026-11-15",
            "text": "[SCHEME]: Test Scheme\nMinimum SIP investment is 100 rupees.",
            "token_count": 26,
        },
        {
            "chunk_id": "test_lock_04",
            "scheme_id": "scheme-test",
            "scheme_name": "Test Scheme Direct",
            "amc": "Test AMC",
            "category": "Equity",
            "section": "lock_in",
            "source_url": "https://example.com/test",
            "last_scraped_date": "2026-11-15",
            "text": "[SCHEME]: Test Scheme\nLock-in period is Nil.",
            "token_count": 22,
        },
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        corpus_file = tmp_path / "corpus.jsonl"
        with open(corpus_file, "w", encoding="utf-8") as f:
            for c in sample_corpus:
                f.write(json.dumps(c) + "\n")

        cache_file = tmp_path / "bm25_test.pkl"

        # 1. Build and save
        indexer = BM25Indexer(corpus_path=corpus_file, index_cache_path=cache_file, auto_load=False)
        summary = indexer.build_index(force_rebuild=True)
        assert summary["status"] == "SUCCESS"
        assert summary["indexed_chunks"] == 4
        assert cache_file.exists()

        # 2. Load from cache
        reloaded = BM25Indexer(corpus_path=corpus_file, index_cache_path=cache_file, auto_load=True)
        assert len(reloaded.chunks) == 4

        # 3. Search on reloaded index (TER should rank #1)
        hits = reloaded.search("TER", k=2)
        assert len(hits) >= 1
        assert hits[0]["chunk_id"] == "test_ter_01"


def test_bm25_exact_acronym_and_keyword_retrieval(shared_bm25_indexer: BM25Indexer):
    """Verify BM25 precision on exact financial acronyms and proper names."""
    # 1. Acronym TER
    ter_hits = shared_bm25_indexer.search("TER of HDFC Flexi Cap", k=3)
    assert len(ter_hits) > 0
    assert ter_hits[0]["chunk_id"] == "hdfc-flexi-cap_expense_ratio"
    assert ter_hits[0]["score"] > 5.0

    # 2. Fund Manager proper name
    mgr_hits = shared_bm25_indexer.search("Who is Amit Ganatra?", k=3)
    assert len(mgr_hits) > 0
    assert mgr_hits[0]["chunk_id"] == "hdfc-flexi-cap_manager_amit-ganatra"
    assert mgr_hits[0]["score"] > 6.0


def test_bm25_metadata_filtering(shared_bm25_indexer: BM25Indexer):
    """Verify BM25 metadata filtering isolates candidates to the specified fund."""
    hits = shared_bm25_indexer.search(
        query="expense ratio and management fees",
        k=5,
        filter_dict={"scheme_id": "hdfc-silver-etf-fof"},
    )
    assert len(hits) > 0
    for h in hits:
        assert h["metadata"]["scheme_id"] == "hdfc-silver-etf-fof"


def test_scheme_entity_resolver():
    """Verify SchemeEntityResolver accurately maps query mentions to canonical scheme_id."""
    resolver = SchemeEntityResolver()

    # Exact and colloquial mentions
    assert resolver.resolve_scheme("What is the TER of HDFC Flexi Cap?") == "hdfc-flexi-cap"
    assert resolver.resolve_scheme("exit load in silver fof") == "hdfc-silver-etf-fof"
    assert resolver.resolve_scheme("Who manages HDFC Balanced Advantage Fund?") == "hdfc-balanced-advantage"
    assert resolver.resolve_scheme("tell me about hdfc large & mid cap fund") == "hdfc-large-and-mid-cap"
    assert resolver.resolve_scheme("hdfc manufacturing fund riskometer") == "hdfc-manufacturing"

    # Ambiguous or non-matching queries should return None
    assert resolver.resolve_scheme("What is the exit load?") is None
    assert resolver.resolve_scheme("Compare HDFC Flexi Cap with Balanced Advantage") is None
    assert resolver.resolve_scheme("What is the weather today?") is None


def test_rrf_scoring_and_ranking_logic():
    """Verify Reciprocal Rank Fusion arithmetic and rank calculation."""
    retriever = HybridRetriever(rrf_k=60)

    # Mock candidate hits
    dense_hits = [
        {"chunk_id": "chunk_A", "score": 0.90, "text": "A", "metadata": {"scheme_id": "s1"}},
        {"chunk_id": "chunk_B", "score": 0.85, "text": "B", "metadata": {"scheme_id": "s1"}},
        {"chunk_id": "chunk_C", "score": 0.80, "text": "C", "metadata": {"scheme_id": "s1"}},
    ]
    sparse_hits = [
        {"chunk_id": "chunk_B", "score": 8.0, "text": "B", "metadata": {"scheme_id": "s1"}},
        {"chunk_id": "chunk_A", "score": 5.0, "text": "A", "metadata": {"scheme_id": "s1"}},
        {"chunk_id": "chunk_D", "score": 4.0, "text": "D", "metadata": {"scheme_id": "s1"}},
    ]

    results = retriever._fuse_rankings(dense_hits=dense_hits, sparse_hits=sparse_hits, top_k=3)
    assert len(results) == 3

    # chunk_A: dense_rank=1, sparse_rank=2 -> 1/61 + 1/62 = 0.016393 + 0.016129 = 0.032522
    # chunk_B: dense_rank=2, sparse_rank=1 -> 1/62 + 1/61 = 0.016129 + 0.016393 = 0.032522
    # chunk_A dense score (0.90) > chunk_B dense score (0.85) -> tie-break chunk_A first
    assert results[0].chunk_id == "chunk_A"
    assert results[1].chunk_id == "chunk_B"
    assert results[0].dense_rank == 1
    assert results[0].sparse_rank == 2


def test_hybrid_retrieval_exit_criteria(hybrid_retriever: HybridRetriever):
    """Verify all explicit Phase 3 acceptance criteria."""
    # 1. Exact acronym TER test
    ter_res = hybrid_retriever.retrieve("TER of HDFC Flexi Cap", k=3)
    assert len(ter_res) > 0
    assert ter_res[0].chunk_id == "hdfc-flexi-cap_expense_ratio"
    assert ter_res[0].section == "expense_ratio"

    # 2. Fund management team test
    mgr_res = hybrid_retriever.retrieve("Who manages HDFC Balanced Advantage Fund?", k=3)
    assert len(mgr_res) > 0
    # Top 1 should be the fund management team overview
    assert mgr_res[0].chunk_id == "hdfc-balanced-advantage_fund_management"

    # 3. Minimum SIP / Investment limits test
    sip_res = hybrid_retriever.retrieve("Can I invest 100 every month in silver?", k=3)
    assert len(sip_res) > 0
    assert sip_res[0].chunk_id == "hdfc-silver-etf-fof_investment_limits"

    # 4. Semantic paraphrase test (penalty for early withdrawal -> exit load)
    early_res = hybrid_retriever.retrieve("Penalty for withdrawing early from HDFC Flexi Cap", k=3)
    assert len(early_res) > 0
    assert early_res[0].chunk_id == "hdfc-flexi-cap_exit_load"

    # 5. Lock-in period test
    lock_res = hybrid_retriever.retrieve("Is there a lock in period for HDFC Silver ETF FoF?", k=3)
    assert len(lock_res) > 0
    assert lock_res[0].chunk_id == "hdfc-silver-etf-fof_lock_in"


def test_hybrid_retrieval_scheme_isolation(hybrid_retriever: HybridRetriever):
    """Verify that scheme filtering strictly confines retrieval to target fund."""
    # Query mentions no scheme, but explicit scheme_id is supplied
    results = hybrid_retriever.retrieve(
        query="What is the exit load and redemption fee?",
        k=3,
        scheme_id="hdfc-manufacturing",
        auto_resolve_scheme=False,
    )
    assert len(results) == 3
    for r in results:
        assert r.scheme_id == "hdfc-manufacturing"


def test_out_of_domain_confidence_detection(hybrid_retriever: HybridRetriever):
    """Verify out-of-domain queries trigger low-confidence flag."""
    # Legitimate factual query
    legit_res = hybrid_retriever.retrieve("What is the exit load of HDFC Flexi Cap?", k=3)
    assert hybrid_retriever.check_confidence(legit_res) is True

    # Out-of-domain queries
    ood_queries = [
        "Recipe for chocolate chip cookies with sea salt",
        "How do I book a hotel in Paris?",
        "Price of Bitcoin in USD today",
    ]
    for q in ood_queries:
        ood_res = hybrid_retriever.retrieve(q, k=3, auto_resolve_scheme=False)
        is_confident = hybrid_retriever.check_confidence(ood_res)
        assert is_confident is False, f"Expected OOD query '{q}' to fail confidence check."
