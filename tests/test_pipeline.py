"""Comprehensive tests for Phase 5: RAG Pipeline, Prompts, LLM Client, and Generation Engine."""

from unittest.mock import MagicMock, patch
import pytest

from src.config import (
    AMFI_INVESTOR_EDUCATION_URL,
    MANDATORY_DISCLAIMER,
    RECENCY_FOOTER_PREFIX,
)
from src.guardrails import QueryIntent
from src.pipeline.llm_client import LLMClient
from src.pipeline.prompts import (
    build_system_prompt,
    build_user_prompt,
    format_context,
)
from src.pipeline.rag_engine import RAGEngine, RAGResponse
from src.retrieval.hybrid_retriever import HybridRetriever, RetrievalResult


# ==============================================================================
# 1. Prompt Engineering Tests
# ==============================================================================

def test_system_prompt_contains_mandatory_constraints():
    """Verify system prompt embeds all non-negotiable compliance rules."""
    prompt = build_system_prompt()
    assert MANDATORY_DISCLAIMER in prompt
    assert "SOURCING CONSTRAINT" in prompt
    assert "REGULATORY & ADVISORY CONSTRAINTS" in prompt
    assert "3 sentences" in prompt
    assert RECENCY_FOOTER_PREFIX in prompt
    assert "The requested detail is not found in official scheme records." in prompt


def test_format_context_empty():
    """Verify format_context fallback behavior when no chunks are provided."""
    context_text, url, date = format_context([])
    assert context_text == ""
    assert url == AMFI_INVESTOR_EDUCATION_URL
    assert date == "2026-11-15"


def test_format_context_with_results():
    """Verify format_context extracts chunks, primary Groww URL, and recency date."""
    mock_results = [
        RetrievalResult(
            chunk_id="hdfc-flexi-cap_overview_chunk_001",
            scheme_id="hdfc-flexi-cap",
            scheme_name="HDFC Flexi Cap Fund Direct-Growth",
            section="Overview",
            source_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
            last_scraped_date="2026-11-15",
            text="Expense ratio is 0.85% inclusive of GST. Minimum SIP amount is ₹100.",
            rrf_score=0.033,
        ),
        RetrievalResult(
            chunk_id="hdfc-flexi-cap_fund_management_chunk_001",
            scheme_id="hdfc-flexi-cap",
            scheme_name="HDFC Flexi Cap Fund Direct-Growth",
            section="Fund Management",
            source_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
            last_scraped_date="2026-11-15",
            text="Fund is managed by Roshi Jain since July 2022.",
            rrf_score=0.016,
        ),
    ]

    context_text, url, date = format_context(mock_results)
    assert "HDFC Flexi Cap Fund Direct-Growth" in context_text
    assert "Expense ratio is 0.85%" in context_text
    assert "Roshi Jain" in context_text
    assert url == "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"
    assert date == "2026-11-15"


def test_build_user_prompt():
    """Verify build_user_prompt injects context, question, and citation instructions."""
    prompt = build_user_prompt(
        query="What is the expense ratio?",
        context_text="Expense ratio is 0.85%.",
        source_url="https://groww.in/test",
        last_scraped_date="2026-11-15",
    )
    assert "What is the expense ratio?" in prompt
    assert "Expense ratio is 0.85%." in prompt
    assert "VERIFIED SOURCE URL: https://groww.in/test" in prompt
    assert "LATEST SOURCE DATE: 2026-11-15" in prompt


# ==============================================================================
# 2. LLM Client & Mock Fallback Tests
# ==============================================================================

def test_llm_client_mock_configuration():
    """Verify LLM client defaults to mock mode when API key is unset/placeholder."""
    client = LLMClient(api_key="gsk_your_groq_api_key_here")
    assert not client.is_live_configured

    empty_client = LLMClient(api_key="")
    assert not empty_client.is_live_configured


def test_llm_client_mock_generate_extraction():
    """Verify offline mock generator extracts accurate facts, source URL, and recency line."""
    client = LLMClient()
    user_prompt = """CONTEXT CHUNKS:
==================================================
[Chunk 1 | Scheme: HDFC Flexi Cap Fund Direct-Growth | Section: Overview | Date: 2026-11-15]
The expense ratio (TER) of HDFC Flexi Cap Fund Direct-Growth is 0.85%. Exit load is 1% if redeemed within 1 year.
==================================================

VERIFIED SOURCE URL: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth
LATEST SOURCE DATE: 2026-11-15

USER QUESTION:
What is the expense ratio of HDFC Flexi Cap Fund?

Respond strictly following the system instructions:
- Fact-based answer in at most 3 sentences.
- Cite the Verified Source URL.
- End with: Last updated from sources: 2026-11-15
"""
    answer = client.generate("system prompt", user_prompt)
    assert "0.85%" in answer
    assert "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth" in answer
    assert "Last updated from sources: 2026-11-15" in answer


def test_llm_client_live_mocked_network_call():
    """Verify live Groq API invocation format and successful parsing using mocked HTTP."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        "The expense ratio of HDFC Flexi Cap Fund is 0.85%.\n\n"
                        "Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth\n"
                        "Last updated from sources: 2026-11-15"
                    )
                }
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    client = LLMClient(api_key="gsk_live_valid_test_key_12345")
    assert client.is_live_configured

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        result = client.generate("sys", "user")
        assert "0.85%" in result
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == "Bearer gsk_live_valid_test_key_12345"


# ==============================================================================
# 3. End-to-End RAG Engine Pipeline Tests
# ==============================================================================

@pytest.fixture(scope="module")
def rag_engine():
    """Instantiate a shared RAGEngine fixture."""
    return RAGEngine()


def test_rag_engine_factual_query_exit_load(rag_engine):
    """Test factual query answering regarding exit load."""
    resp: RAGResponse = rag_engine.answer("What is the exit load for HDFC Balanced Advantage Fund?")
    assert not resp.is_refusal
    assert not resp.is_fallback
    assert resp.intent == QueryIntent.FACTUAL
    assert resp.scheme_id == "hdfc-balanced-advantage"
    assert "groww.in" in resp.citation_url
    assert "Last updated from sources:" in resp.answer
    assert resp.confidence_score > 0.0
    assert len(resp.retrieved_chunks) > 0


def test_rag_engine_factual_query_fund_manager(rag_engine):
    """Test factual query answering regarding fund manager."""
    resp: RAGResponse = rag_engine.answer("Who is the fund manager of HDFC Flexi Cap Fund?")
    assert not resp.is_refusal
    assert not resp.is_fallback
    assert resp.intent == QueryIntent.FACTUAL
    assert resp.scheme_id == "hdfc-flexi-cap"
    assert "Amit Ganatra" in resp.answer or "Dhruv Muchhal" in resp.answer
    assert "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth" in resp.citation_url
    assert "Last updated from sources:" in resp.answer


def test_rag_engine_factual_query_min_sip(rag_engine):
    """Test factual query answering regarding minimum SIP amount."""
    resp: RAGResponse = rag_engine.answer("What is the minimum SIP amount for HDFC Silver ETF FoF?")
    assert not resp.is_refusal
    assert not resp.is_fallback
    assert resp.intent == QueryIntent.FACTUAL
    assert resp.scheme_id == "hdfc-silver-etf-fof"
    assert "100" in resp.answer or "₹" in resp.answer
    assert "groww.in" in resp.citation_url


def test_rag_engine_advisory_refusal(rag_engine):
    """Test that advisory queries are immediately refused with AMFI link and 0 LLM cost."""
    resp: RAGResponse = rag_engine.answer("Should I invest in HDFC Flexi Cap Fund for retirement?")
    assert resp.is_refusal
    assert not resp.is_fallback
    assert resp.intent == QueryIntent.ADVISORY
    assert "do not provide investment advice" in resp.answer.lower()
    assert AMFI_INVESTOR_EDUCATION_URL in resp.answer
    assert len(resp.retrieved_chunks) == 0  # Retrieval skipped


def test_rag_engine_comparison_refusal(rag_engine):
    """Test that comparison queries are refused deterministically."""
    resp: RAGResponse = rag_engine.answer("Which is better HDFC Flexi Cap or HDFC Large and Mid Cap?")
    assert resp.is_refusal
    assert resp.intent == QueryIntent.COMPARISON
    assert "cannot subjectively rank or compare" in resp.answer.lower()
    assert len(resp.retrieved_chunks) == 0


def test_rag_engine_pii_violation_blocked(rag_engine):
    """Test that queries containing personal financial identifiers are blocked."""
    resp: RAGResponse = rag_engine.answer("My folio number is 1234567/89. Tell me my exit load in HDFC Flexi Cap.")
    assert resp.is_refusal
    assert resp.intent == QueryIntent.PII_VIOLATION
    assert resp.pii_redacted
    assert "personal financial identifiers" in resp.answer.lower()
    assert len(resp.retrieved_chunks) == 0


def test_rag_engine_low_confidence_fallback(rag_engine):
    """Test that out-of-domain or ungrounded queries trigger factual fallback."""
    # Completely unrelated query that passes PII and intent, but has low retrieval similarity
    resp: RAGResponse = rag_engine.answer("What is the culinary recipe for Italian pasta bolognese?")
    assert resp.is_fallback or resp.is_refusal
    if resp.is_fallback:
        assert "not found in official scheme records" in resp.answer.lower()
        assert resp.confidence_score < 0.65


def test_rag_response_serialization(rag_engine):
    """Test RAGResponse to_dict method contains all analytics metadata."""
    resp: RAGResponse = rag_engine.answer("What is the expense ratio of HDFC Manufacturing Fund?")
    d = resp.to_dict()
    assert "query" in d
    assert "answer" in d
    assert "intent" in d
    assert "is_refusal" in d
    assert "is_fallback" in d
    assert "citation_url" in d
    assert "last_updated_date" in d
    assert "confidence_score" in d
    assert "latency_ms" in d
    assert d["latency_ms"] >= 0.0
    assert d["retrieved_chunks_count"] > 0
