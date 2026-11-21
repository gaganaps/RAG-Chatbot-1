"""Multi-tiered intent classification and regulatory policy routing engine."""

from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.config import (
    AMFI_INVESTOR_EDUCATION_URL,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    SEBI_INVESTOR_PORTAL_URL,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class QueryIntent(str, Enum):
    """Categorical classification of user query intent."""
    FACTUAL = "FACTUAL"
    ADVISORY = "ADVISORY"
    COMPARISON = "COMPARISON"
    RETURN_PREDICTION = "RETURN_PREDICTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    PII_VIOLATION = "PII_VIOLATION"


# Regulatory compliant refusal templates
REFUSAL_MESSAGES: Dict[QueryIntent, str] = {
    QueryIntent.ADVISORY: (
        "I am a facts-only assistant and do not provide investment advice, personal recommendations, "
        "or opinion-based evaluations. Please consult a SEBI-registered financial advisor or explore "
        f"investor education materials at AMFI: {AMFI_INVESTOR_EDUCATION_URL}"
    ),
    QueryIntent.COMPARISON: (
        "I cannot subjectively rank or compare mutual fund schemes against each other. "
        "You can inspect factual parameters (such as expense ratio, exit load, minimum investment, "
        "and riskometer) for each fund individually. For investor education, visit: "
        f"{AMFI_INVESTOR_EDUCATION_URL}"
    ),
    QueryIntent.RETURN_PREDICTION: (
        "Mutual fund investments are subject to market risks, and future returns or profits cannot "
        "be predicted or guaranteed. For historical disclosures and official scheme documents, "
        "please refer to the official factsheets at: https://www.hdfcfund.com"
    ),
    QueryIntent.OUT_OF_SCOPE: (
        "I am a specialized facts-only assistant for HDFC Mutual Fund schemes. "
        "I can answer factual questions regarding expense ratios (TER), exit loads, minimum SIP/lumpsum limits, "
        f"fund managers, lock-in periods, riskometer ratings, and benchmarks. See: {AMFI_INVESTOR_EDUCATION_URL}"
    ),
    QueryIntent.PII_VIOLATION: (
        "For your security and privacy, please do not share personal financial identifiers or credentials "
        "(such as PAN, Aadhaar, bank account details, folio numbers, phone numbers, or emails)."
    ),
}


@dataclass
class IntentRoutingDecision:
    """Decision object produced by the intent router."""
    intent: QueryIntent
    is_allowed_for_rag: bool
    refusal_message: Optional[str] = None
    reasoning: str = ""
    confidence: float = 1.0


class IntentClassifier:
    """Deterministic and LLM-backed intent classification and policy router."""

    # High-precision regex pattern matchers for deterministic routing (< 1ms)
    ADVISORY_PATTERNS: List[re.Pattern] = [
        re.compile(r"\b(?:should\s+i|i\s+should)\s+(?:invest|buy|put|start|choose|pick|switch|redeem|hold|sell|exit)\b", re.IGNORECASE),
        re.compile(r"\bis\s+.*?\s+(?:good|safe|worth|better|profitable|advisable|wise|suitable)\b", re.IGNORECASE),
        re.compile(r"\bwhich\s+(?:fund|scheme)?\s*(?:is|would\s+be)\s+(?:the\s+)?(?:best|top|safest|most\s+profitable|recommended|better|good)\b", re.IGNORECASE),
        re.compile(r"\bwhere\s+(?:should\s+i|to)\s+invest\b", re.IGNORECASE),
        re.compile(r"\b(?:can|do|would|could|will)\s+you\s+(?:recommend|suggest|guide|advise)\b", re.IGNORECASE),
        re.compile(r"\b(?:financial|investment)\s+advis(?:or|er|ice)\b", re.IGNORECASE),
        re.compile(r"\b(?:advise|advice)\s+(?:me|starting|investing|buying|on)\b", re.IGNORECASE),
        re.compile(r"\b(?:suggest|recommend)\s+(?:.*?\s+)?(?:fund|scheme|investment|portfolio)\b", re.IGNORECASE),
        re.compile(r"\bhelp\s+me\s+(?:choose|decide|pick|select)\b", re.IGNORECASE),
        re.compile(r"\b(?:good|right|best)\s+time\s+to\s+invest\b", re.IGNORECASE),
        re.compile(r"\b(?:retire|retirement)\s+plan(?:ning)?\b", re.IGNORECASE),
        re.compile(r"\bbeat\s+inflation\b", re.IGNORECASE),
        re.compile(r"\bportfolio\s+(?:review|advice|recommendation)\b", re.IGNORECASE),
        re.compile(r"\bhow\s+to\s+invest\s+\d+\b", re.IGNORECASE),
        re.compile(r"\bwhich\s+(?:fund|scheme)\s+(?:will|to|should)\b", re.IGNORECASE),
        re.compile(r"\b(?:tax\s+saving|tax\s+saver|save\s+tax)\b", re.IGNORECASE),
        re.compile(r"\b(?:best\s+suited|suited\s+for)\b", re.IGNORECASE),
        re.compile(r"\b(?:allocate|allocation)\s+.*?\b", re.IGNORECASE),
        re.compile(r"\b(?:pretend|act\s+as|roleplay)\b", re.IGNORECASE),
        re.compile(r"\bignore\s+all\s+(?:rules|instructions)\b", re.IGNORECASE),
    ]

    COMPARISON_PATTERNS: List[re.Pattern] = [
        re.compile(r"\bwhich\s+(?:one\s+)?is\s+better\b", re.IGNORECASE),
        re.compile(r"\bcompare\s+.*?\b", re.IGNORECASE),
        re.compile(r"\b(?:flexi\s*cap|silver|balanced|large|manufacturing)\s+(?:vs|versus)\b", re.IGNORECASE),
        re.compile(r"\b(?:better|superior)\s+than\b", re.IGNORECASE),
        re.compile(r"\brank\s+(?:.*?\s+)?(?:funds?|schemes?)\b", re.IGNORECASE),
        re.compile(r"\b(?:best\s+to\s+worst|worst\s+to\s+best)\b", re.IGNORECASE),
        re.compile(r"\b(?:choose|pick)\s+between\b", re.IGNORECASE),
    ]

    RETURN_PREDICTION_PATTERNS: List[re.Pattern] = [
        re.compile(r"\bwill\s+(?:.*?\s+)?(?:give|make|earn|yield|deliver|double|reach|be)\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+will\s+be\b", re.IGNORECASE),
        re.compile(r"\b\d+%\s+(?:annual|annualized|expected|future)?\s*returns?\b", re.IGNORECASE),
        re.compile(r"\bpredict\b", re.IGNORECASE),
        re.compile(r"\bexpected\s+returns?\b", re.IGNORECASE),
        re.compile(r"\bhow\s+much\s+(?:profit|money|return|returns)\s+will\s+i\s+(?:make|get|earn)\b", re.IGNORECASE),
        re.compile(r"\bfuture\s+returns?\b", re.IGNORECASE),
        re.compile(r"\b(?:guaranteed|promised)\s+returns?\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+returns?\s+can\s+i\s+expect\b", re.IGNORECASE),
        re.compile(r"\bdouble\s+in\s+\d+\s*(?:years?|months?)\b", re.IGNORECASE),
        re.compile(r"\bwill\s+it\s+double\b", re.IGNORECASE),
        re.compile(r"\b(?:next\s+(?:month|year|week)|in\s+(?:the\s+)?future)\b", re.IGNORECASE),
    ]

    FACTUAL_KEYWORDS: List[str] = [
        "ter", "expense ratio", "expense", "exit load", "exit fee", "redemption",
        "penalty", "sip", "lumpsum", "minimum investment", "min sip", "min lumpsum",
        "fund manager", "who manages", "who is running", "managed by", "education",
        "lock in", "lock-in", "riskometer", "risk rating", "benchmark",
        "tri", "factsheet", "overview", "nav", "aum", "category", "launch date",
    ]

    def __init__(
        self,
        use_llm_fallback: bool = True,
        groq_api_key: Optional[str] = None,
        groq_model: str = GROQ_MODEL,
    ):
        """Initialize the intent classifier.
        
        Args:
            use_llm_fallback: If True, uses Groq LLM when deterministic regex is inconclusive.
            groq_api_key: Optional API key override; defaults to GROQ_API_KEY environment variable.
            groq_model: Groq model to invoke for fallback classification.
        """
        self.use_llm_fallback = use_llm_fallback
        self.groq_api_key = groq_api_key or GROQ_API_KEY
        self.groq_model = groq_model

    def classify_deterministic(self, text: str) -> Optional[QueryIntent]:
        """Fast regex & keyword rule classification (< 1ms)."""
        q_clean = text.strip()

        # 1. Comparison checks (comparative terms: better, compare, vs, rank)
        for pat in self.COMPARISON_PATTERNS:
            if pat.search(q_clean):
                return QueryIntent.COMPARISON

        # 2. Return prediction checks
        for pat in self.RETURN_PREDICTION_PATTERNS:
            if pat.search(q_clean):
                return QueryIntent.RETURN_PREDICTION

        # 3. Advisory checks
        for pat in self.ADVISORY_PATTERNS:
            if pat.search(q_clean):
                return QueryIntent.ADVISORY

        # 4. Factual keyword check
        q_lower = q_clean.lower()
        for kw in self.FACTUAL_KEYWORDS:
            if kw in q_lower:
                return QueryIntent.FACTUAL

        return None

    def classify_with_groq_llm(self, text: str) -> QueryIntent:
        """Fallback classification using Groq Llama 3.3 70B for nuanced queries."""
        if not self.groq_api_key or self.groq_api_key.startswith("gsk_your_"):
            logger.info("Groq API key not configured. Using deterministic heuristic fallback.")
            return self._heuristic_fallback(text)

        try:
            import httpx

            url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json",
            }

            prompt = (
                "You are an intent classifier for an Indian mutual fund regulatory compliance system.\n"
                "Classify the following user query into exactly ONE category:\n"
                "- FACTUAL (question asks for verifiable data like TER, exit load, fund managers, min SIP, riskometer, benchmark)\n"
                "- ADVISORY (user asks for investment advice, suitability, opinion, 'should I invest', 'which is best')\n"
                "- COMPARISON (user asks to compare or rank two or more funds subjectively)\n"
                "- RETURN_PREDICTION (user asks to predict future returns or profit)\n"
                "- OUT_OF_SCOPE (non-mutual-fund or completely unrelated queries)\n\n"
                f"Query: \"{text}\"\n\n"
                "Respond in valid JSON format only: {\"intent\": \"<CATEGORY>\"}"
            )

            payload = {
                "model": self.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 50,
            }

            with httpx.Client(timeout=6.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                raw_content = resp.json()["choices"][0]["message"]["content"].strip()

            # Extract JSON from potential markdown blocks
            json_match = re.search(r"\{.*?\}", raw_content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                intent_str = data.get("intent", "").upper()
                if hasattr(QueryIntent, intent_str):
                    return QueryIntent[intent_str]

        except Exception as e:
            logger.warning(f"Groq LLM intent classification failed: {e}. Falling back to heuristic.")

        return self._heuristic_fallback(text)

    def _heuristic_fallback(self, text: str) -> QueryIntent:
        """Default heuristic when LLM is unavailable and rules are inconclusive."""
        q_lower = text.lower()
        mutual_fund_tokens = ["fund", "hdfc", "scheme", "direct", "growth", "amc", "mutual"]
        if any(t in q_lower for t in mutual_fund_tokens):
            return QueryIntent.FACTUAL
        return QueryIntent.OUT_OF_SCOPE

    def route_query(self, query: str) -> IntentRoutingDecision:
        """Route user query and generate compliant decision or refusal.
        
        Args:
            query: User input query string.
            
        Returns:
            IntentRoutingDecision object.
        """
        cleaned_query = query.strip()
        if not cleaned_query:
            return IntentRoutingDecision(
                intent=QueryIntent.OUT_OF_SCOPE,
                is_allowed_for_rag=False,
                refusal_message=REFUSAL_MESSAGES[QueryIntent.OUT_OF_SCOPE],
                reasoning="Empty query provided.",
            )

        # Step 1: Run fast deterministic classifier (< 1ms)
        intent = self.classify_deterministic(cleaned_query)

        # Step 2: If inconclusive, optionally invoke Groq LLM
        if intent is None:
            if self.use_llm_fallback and self.groq_api_key and not self.groq_api_key.startswith("gsk_your_"):
                logger.info(f"Invoking Groq LLM fallback classifier for query: '{cleaned_query}'")
                intent = self.classify_with_groq_llm(cleaned_query)
            else:
                intent = self._heuristic_fallback(cleaned_query)

        is_allowed = intent == QueryIntent.FACTUAL
        refusal = REFUSAL_MESSAGES.get(intent) if not is_allowed else None

        decision = IntentRoutingDecision(
            intent=intent,
            is_allowed_for_rag=is_allowed,
            refusal_message=refusal,
            reasoning=f"Classified as {intent.value}.",
        )

        if not is_allowed:
            logger.info(f"Query intercepted by guardrails: Intent={intent.value}")

        return decision
