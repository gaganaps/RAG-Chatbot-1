"""System prompts, context formatters, and prompt templates for facts-only mutual fund RAG."""

from typing import List, Optional, Tuple
from src.config import (
    ALLOWED_CITATION_DOMAINS,
    AMFI_INVESTOR_EDUCATION_URL,
    MANDATORY_DISCLAIMER,
    MAX_RESPONSE_SENTENCES,
    RECENCY_FOOTER_PREFIX,
)
from src.retrieval.hybrid_retriever import RetrievalResult

# Base System Prompt enforcing facts-only, anti-hallucination, and strict formatting
SYSTEM_PROMPT = f"""You are a strict, facts-only Mutual Fund FAQ Assistant for HDFC Mutual Funds on Groww.
{MANDATORY_DISCLAIMER}

NON-NEGOTIABLE OPERATIONAL CONSTRAINTS:
1. SOURCING CONSTRAINT:
   - Base your answer EXCLUSIVELY on the provided Context Chunks.
   - Do NOT use any pre-trained external knowledge, assumptions, or extrapolations.
   - If the exact factual answer is NOT explicitly stated in the context, output EXACTLY:
     "The requested detail is not found in official scheme records."

2. REGULATORY & ADVISORY CONSTRAINTS:
   - Provide ZERO investment advice, recommendations, buy/sell opinions, or performance predictions.
   - Maintain an objective, neutral, institutional tone.

3. LENGTH CONSTRAINT:
   - The answer body must be concise and strictly AT MOST {MAX_RESPONSE_SENTENCES} sentences.

4. CITATION & RECENCY CONSTRAINTS:
   - You MUST include exactly ONE verified source URL provided in the context under "Source: <URL>".
   - You MUST end your response with the exact recency footer provided in the context:
     "{RECENCY_FOOTER_PREFIX} <YYYY-MM-DD>"

OUTPUT FORMAT (Follow this exact layout):
<Answer body in 1 to 3 concise, factual sentences>

Source: <URL>
{RECENCY_FOOTER_PREFIX} <YYYY-MM-DD>
"""


def build_system_prompt() -> str:
    """Return the finalized system prompt."""
    return SYSTEM_PROMPT.strip()


def format_context(results: List[RetrievalResult]) -> Tuple[str, str, str]:
    """Format a list of RetrievalResults into structured context for the LLM.
    
    Args:
        results: Top-k RetrievalResult objects from HybridRetriever.
        
    Returns:
        Tuple of (context_text, primary_source_url, latest_scraped_date).
    """
    if not results:
        return "", AMFI_INVESTOR_EDUCATION_URL, "2026-11-15"

    context_blocks: List[str] = []
    primary_source_url = results[0].source_url
    latest_scraped_date = results[0].last_scraped_date or "2026-11-15"

    for i, res in enumerate(results, start=1):
        # Pick the most specific scheme URL if available
        if res.source_url and "groww.in" in res.source_url:
            primary_source_url = res.source_url
        if res.last_scraped_date:
            latest_scraped_date = res.last_scraped_date

        block = (
            f"[Chunk {i} | Scheme: {res.scheme_name} | Section: {res.section} | Date: {res.last_scraped_date}]\n"
            f"{res.text.strip()}"
        )
        context_blocks.append(block)

    formatted_context = "\n\n---\n\n".join(context_blocks)
    return formatted_context, primary_source_url, latest_scraped_date


def build_user_prompt(
    query: str,
    context_text: str,
    source_url: str,
    last_scraped_date: str,
) -> str:
    """Assemble user prompt injecting context chunks, user question, and required metadata.
    
    Args:
        query: User's sanitized question.
        context_text: Formatted context chunk string.
        source_url: Primary verified citation URL.
        last_scraped_date: ISO date string for recency footer.
        
    Returns:
        Rendered user prompt string.
    """
    return f"""CONTEXT CHUNKS:
==================================================
{context_text}
==================================================

VERIFIED SOURCE URL: {source_url}
LATEST SOURCE DATE: {last_scraped_date}

USER QUESTION:
{query}

Respond strictly following the system instructions:
- Fact-based answer in at most 3 sentences.
- Cite the Verified Source URL.
- End with: {RECENCY_FOOTER_PREFIX} {last_scraped_date}
"""
