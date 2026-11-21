"""End-to-End RAG Pipeline Orchestrator integrating Guardrails, Hybrid Retrieval, and LLM Generation."""

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, List, Optional

from src.config import (
    ACTIVE_SCHEMES,
    AMFI_INVESTOR_EDUCATION_URL,
    RECENCY_FOOTER_PREFIX,
    SIMILARITY_CONFIDENCE_THRESHOLD,
)
from src.guardrails import GuardrailResult, InputGuardrails, OutputGuardrails, QueryIntent
from src.pipeline.llm_client import LLMClient
from src.pipeline.prompts import (
    build_system_prompt,
    build_user_prompt,
    format_context,
)
from src.retrieval.hybrid_retriever import HybridRetriever, RetrievalResult

logger = logging.getLogger(__name__)


@dataclass
class RAGResponse:
    """Standardized end-to-end response unit from the Mutual Fund RAG system."""
    query: str
    answer: str
    intent: QueryIntent
    is_refusal: bool
    is_fallback: bool
    citation_url: str
    last_updated_date: str
    confidence_score: float
    retrieved_chunks: List[RetrievalResult] = field(default_factory=list)
    scheme_id: Optional[str] = None
    scheme_name: Optional[str] = None
    pii_redacted: bool = False
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert RAGResponse to a serializable dictionary."""
        return {
            "query": self.query,
            "answer": self.answer,
            "intent": self.intent.value,
            "is_refusal": self.is_refusal,
            "is_fallback": self.is_fallback,
            "citation_url": self.citation_url,
            "last_updated_date": self.last_updated_date,
            "confidence_score": round(self.confidence_score, 4),
            "scheme_id": self.scheme_id,
            "scheme_name": self.scheme_name,
            "pii_redacted": self.pii_redacted,
            "latency_ms": round(self.latency_ms, 2),
            "retrieved_chunks_count": len(self.retrieved_chunks),
            "retrieved_chunks": [c.to_dict() for c in self.retrieved_chunks],
        }


class RAGEngine:
    """Core RAG engine coordinating Input Guardrails -> Hybrid Retrieval -> Prompt Assembly -> LLM Generation."""

    def __init__(
        self,
        guardrails: Optional[InputGuardrails] = None,
        retriever: Optional[HybridRetriever] = None,
        llm_client: Optional[LLMClient] = None,
        output_guard: Optional[OutputGuardrails] = None,
    ):
        """Initialize the RAG pipeline components.
        
        Args:
            guardrails: Input guardrail instance (PII filter + Intent routing).
            retriever: Hybrid retriever combining ChromaDB dense + Rank-BM25 with RRF.
            llm_client: LLM inference client (Groq Llama 3.3 70B / offline fallback).
            output_guard: Programmatic post-processing output compliance guardrails.
        """
        self.guardrails = guardrails or InputGuardrails()
        self.retriever = retriever or HybridRetriever()
        self.llm_client = llm_client or LLMClient()
        self.output_guard = output_guard or OutputGuardrails()
        self.system_prompt = build_system_prompt()

    def answer(self, query: str, top_k: int = 4) -> RAGResponse:
        """Process a mutual fund question through the guarded RAG pipeline.
        
        Args:
            query: User's raw question string.
            top_k: Number of context chunks to retrieve.
            
        Returns:
            RAGResponse object with answer body, citation URL, recency footer, and provenance metadata.
        """
        start_time = time.perf_counter()
        query_stripped = query.strip()

        # ----------------------------------------------------------------------
        # Stage 1: Input Guardrails (PII Detection & Regulatory Intent Routing)
        # ----------------------------------------------------------------------
        guard_result: GuardrailResult = self.guardrails.validate(query_stripped)

        # If blocked (PII violation, Advisory, Comparison, Return Prediction, Out of Scope)
        if not guard_result.is_allowed:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            
            # Resolve scheme URL if mentioned, else default to AMFI educational portal
            scheme_id = self.retriever.entity_resolver.resolve(query_stripped)
            scheme_cfg = ACTIVE_SCHEMES.get(scheme_id) if scheme_id else None
            citation_url = scheme_cfg.groww_url if scheme_cfg else AMFI_INVESTOR_EDUCATION_URL
            scheme_name = scheme_cfg.scheme_name if scheme_cfg else None

            logger.info(
                "Input blocked by Guardrails [Intent: %s, Latency: %.2f ms]",
                guard_result.intent.value,
                latency_ms,
            )

            return RAGResponse(
                query=query_stripped,
                answer=guard_result.message or "Query violates compliance policy.",
                intent=guard_result.intent,
                is_refusal=True,
                is_fallback=False,
                citation_url=citation_url,
                last_updated_date="2026-11-15",
                confidence_score=1.0,
                retrieved_chunks=[],
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                pii_redacted=bool(guard_result.detected_pii),
                latency_ms=latency_ms,
            )

        # ----------------------------------------------------------------------
        # Stage 2: Hybrid Retrieval & Confidence Gating
        # ----------------------------------------------------------------------
        effective_query = guard_result.sanitized_query or query_stripped
        retrieved_chunks: List[RetrievalResult] = self.retriever.retrieve(
            query=effective_query,
            top_k=top_k,
        )

        is_confident = self.retriever.check_confidence(retrieved_chunks)
        conf_score = (
            retrieved_chunks[0].dense_score
            if retrieved_chunks and retrieved_chunks[0].dense_score is not None
            else (retrieved_chunks[0].rrf_score if retrieved_chunks else 0.0)
        )

        # Resolve scheme metadata from chunks or entity resolver
        scheme_id = None
        scheme_name = None
        if retrieved_chunks:
            scheme_id = retrieved_chunks[0].scheme_id
            scheme_name = retrieved_chunks[0].scheme_name
        else:
            scheme_id = self.retriever.entity_resolver.resolve(effective_query)
            if scheme_id and scheme_id in ACTIVE_SCHEMES:
                scheme_name = ACTIVE_SCHEMES[scheme_id].scheme_name

        # If low retrieval confidence or empty chunks -> Factual Fallback
        if not is_confident or not retrieved_chunks:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            scheme_cfg = ACTIVE_SCHEMES.get(scheme_id) if scheme_id else None
            citation_url = scheme_cfg.groww_url if scheme_cfg else AMFI_INVESTOR_EDUCATION_URL
            source_date = "2026-11-15"

            fallback_answer = (
                "The requested detail is not found in official scheme records for the selected mutual fund.\n\n"
                f"Source: {citation_url}\n"
                f"{RECENCY_FOOTER_PREFIX} {source_date}"
            )

            logger.info(
                "Low retrieval confidence (score: %.3f < threshold: %.2f). Emitting factual fallback.",
                conf_score,
                SIMILARITY_CONFIDENCE_THRESHOLD,
            )

            return RAGResponse(
                query=query_stripped,
                answer=fallback_answer,
                intent=guard_result.intent,
                is_refusal=False,
                is_fallback=True,
                citation_url=citation_url,
                last_updated_date=source_date,
                confidence_score=conf_score,
                retrieved_chunks=retrieved_chunks,
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                pii_redacted=bool(guard_result.detected_pii),
                latency_ms=latency_ms,
            )

        # ----------------------------------------------------------------------
        # Stage 3: Prompt Construction & Context Assembly
        # ----------------------------------------------------------------------
        context_text, citation_url, last_scraped_date = format_context(retrieved_chunks)
        user_prompt = build_user_prompt(
            query=effective_query,
            context_text=context_text,
            source_url=citation_url,
            last_scraped_date=last_scraped_date,
        )

        # ----------------------------------------------------------------------
        # Stage 4: LLM Generation
        # ----------------------------------------------------------------------
        generated_answer = self.llm_client.generate(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
        )

        # ----------------------------------------------------------------------
        # Stage 5: Output Guardrails (Sentence Length, Single Whitelist URL, Recency)
        # ----------------------------------------------------------------------
        guarded_result = self.output_guard.enforce(
            raw_output=generated_answer,
            verified_url=citation_url,
            verified_date=last_scraped_date,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        logger.info(
            "RAG generation completed for '%s' in %.2f ms [Confidence: %.3f, Sentences: %d]",
            effective_query[:40],
            latency_ms,
            conf_score,
            guarded_result.sentence_count,
        )

        return RAGResponse(
            query=query_stripped,
            answer=guarded_result.cleaned_output,
            intent=guard_result.intent,
            is_refusal=False,
            is_fallback=False,
            citation_url=guarded_result.citation_url,
            last_updated_date=guarded_result.recency_date,
            confidence_score=conf_score,
            retrieved_chunks=retrieved_chunks,
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            pii_redacted=bool(guard_result.detected_pii),
            latency_ms=latency_ms,
        )
