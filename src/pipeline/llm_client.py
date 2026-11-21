"""Pluggable Free LLM Client supporting Groq (Llama 3.3 70B / 3.1 8B) with offline fallback."""

import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx

from src.config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    LLM_PROVIDER,
    RECENCY_FOOTER_PREFIX,
)

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified client for invoking free LLMs (Groq OpenAI-compatible API) with resilient offline mode."""

    FALLBACK_MODELS = [
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-20b",
    ]

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout: float = 20.0,
    ):
        """Initialize the LLM client.
        
        Args:
            provider: LLM provider identifier ("groq").
            api_key: Secret API key for authentication.
            model: Model identifier (defaults to GROQ_MODEL or openai/gpt-oss-120b).
            base_url: API endpoint URL.
            temperature: Sampling temperature (0.0 for deterministic factual answers).
            max_tokens: Maximum completion tokens (1024 to accommodate reasoning models).
            timeout: Network request timeout in seconds.
        """
        self.provider = (provider or LLM_PROVIDER or "groq").lower()
        self.api_key = api_key if api_key is not None else (GROQ_API_KEY or os.getenv("GROQ_API_KEY", ""))
        self.model = model or GROQ_MODEL or "openai/gpt-oss-120b"
        self.base_url = (base_url or GROQ_BASE_URL or "https://api.groq.com/openai/v1").rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @property
    def is_live_configured(self) -> bool:
        """Check whether valid live API credentials are configured."""
        if not self.api_key:
            return False
        if "your_groq_api_key_here" in self.api_key:
            return False
        if os.getenv("MOCK_LLM", "").lower() in ("1", "true", "yes"):
            return False
        return True

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate response from LLM or offline fallback.
        
        Args:
            system_prompt: Operational system instructions.
            user_prompt: User prompt containing context, query, and citation metadata.
            
        Returns:
            Generated response string.
        """
        if not self.is_live_configured:
            logger.info("Using deterministic offline generator (no live GROQ_API_KEY set).")
            return self._mock_generate(system_prompt, user_prompt)

        try:
            return self._call_groq(system_prompt, user_prompt)
        except Exception as e:
            logger.warning(
                "Groq API call encountered an error (%s: %s). Falling back to offline generator.",
                type(e).__name__,
                e,
            )
            return self._mock_generate(system_prompt, user_prompt)

    def _call_groq(self, system_prompt: str, user_prompt: str) -> str:
        """Call Groq API using standard HTTP client with automatic model fallback."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Models to attempt: primary model first, then known active fallbacks
        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]

        last_error = None
        with httpx.Client(timeout=self.timeout) as client:
            for model_name in models_to_try:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }

                try:
                    resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code == 404:
                        # Model not available on this account, try next candidate
                        logger.info("Groq model '%s' not found (404). Trying next fallback.", model_name)
                        continue
                    resp.raise_for_status()
                    data = resp.json()

                    choice = data["choices"][0]
                    content = (choice["message"].get("content") or "").strip()
                    if not content and choice["message"].get("reasoning"):
                        content = choice["message"]["reasoning"].strip()

                    if content:
                        return content
                except Exception as err:
                    last_error = err
                    logger.warning("Groq attempt with model '%s' failed: %s", model_name, err)
                    continue

        if last_error:
            raise last_error
        raise RuntimeError("All Groq model attempts failed.")

    def _mock_generate(self, system_prompt: str, user_prompt: str) -> str:
        """Deterministic context-extractive generator for testing and offline execution.
        
        Extracts factual sentences directly answering the user question from the injected context chunks.
        """
        # Extract source url and date from user prompt
        source_url_match = re.search(r"VERIFIED SOURCE URL:\s*(\S+)", user_prompt)
        source_url = source_url_match.group(1) if source_url_match else "https://groww.in"

        date_match = re.search(r"LATEST SOURCE DATE:\s*(\S+)", user_prompt)
        source_date = date_match.group(1) if date_match else "2026-11-15"

        # Extract context block
        context_match = re.search(r"CONTEXT CHUNKS:\n=+\n(.*?)\n=+", user_prompt, re.DOTALL)
        context_text = context_match.group(1) if context_match else ""

        # Extract user question
        q_match = re.search(r"USER QUESTION:\s*\n(.*?)\n\nRespond strictly", user_prompt, re.DOTALL)
        query = q_match.group(1).strip().lower() if q_match else ""

        if not context_text.strip():
            return (
                f"The requested detail is not found in official scheme records.\n\n"
                f"Source: {source_url}\n"
                f"{RECENCY_FOOTER_PREFIX} {source_date}"
            )

        # Split context into clean sentences
        raw_sentences = []
        for line in context_text.splitlines():
            line = line.strip()
            if not line or line.startswith("[Chunk") or line.startswith("---") or line.startswith("#"):
                continue
            # Split line into sentences
            s_list = re.split(r"(?<=[.!?])\s+", line)
            for s in s_list:
                s_clean = s.strip()
                if len(s_clean) > 10:
                    raw_sentences.append(s_clean)

        # Keyword mapping for high-precision extraction
        keywords: List[str] = []
        if "expense" in query or "ter" in query or "ratio" in query:
            keywords = ["expense ratio", "expense", "ter", "%"]
        elif "exit load" in query or "exit" in query:
            keywords = ["exit load", "redeem", "days", "months", "%"]
        elif "manager" in query or "managed" in query:
            keywords = ["fund manager", "manager", "managed by", "since", "experience"]
        elif "sip" in query or "minimum" in query or "lumpsum" in query or "investment" in query:
            keywords = ["minimum sip", "sip", "lumpsum", "min", "₹"]
        elif "lock-in" in query or "lock in" in query:
            keywords = ["lock-in", "lock in", "period", "years", "elss"]
        elif "riskometer" in query or "risk" in query:
            keywords = ["riskometer", "very high", "high", "moderate", "risk"]
        elif "benchmark" in query:
            keywords = ["benchmark", "nifty", "tri", "index", "domestic price"]
        else:
            # General query words
            keywords = [w for w in re.findall(r"\w+", query) if len(w) > 3 and w not in ("what", "which", "when", "where", "fund", "hdfc")]

        selected_sentences: List[str] = []
        for sent in raw_sentences:
            sent_lower = sent.lower()
            if any(k.lower() in sent_lower for k in keywords):
                if sent not in selected_sentences:
                    selected_sentences.append(sent)
            if len(selected_sentences) >= 2:
                break

        # If no keyword matched, take the first 1-2 informative sentences
        if not selected_sentences:
            for sent in raw_sentences:
                if len(sent) > 20 and not sent.startswith("Source:") and not sent.startswith("Groww"):
                    selected_sentences.append(sent)
                if len(selected_sentences) >= 2:
                    break

        if not selected_sentences:
            body = "The requested detail is not found in official scheme records."
        else:
            # Limit strictly to at most 3 sentences
            body = " ".join(selected_sentences[:3])

        return (
            f"{body}\n\n"
            f"Source: {source_url}\n"
            f"{RECENCY_FOOTER_PREFIX} {source_date}"
        )
