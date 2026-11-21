"""Input guardrails module for PII sanitization and regulatory intent routing."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.guardrails.intent_classifier import (
    IntentClassifier,
    IntentRoutingDecision,
    QueryIntent,
    REFUSAL_MESSAGES,
)
from src.guardrails.output_guard import OutputGuardrailResult, OutputGuardrails
from src.guardrails.pii_filter import PII_SECURITY_WARNING, PIICheckResult, PIIFilter

__all__ = [
    "PIIFilter",
    "PIICheckResult",
    "PII_SECURITY_WARNING",
    "IntentClassifier",
    "IntentRoutingDecision",
    "QueryIntent",
    "REFUSAL_MESSAGES",
    "InputGuardrails",
    "GuardrailResult",
    "OutputGuardrails",
    "OutputGuardrailResult",
]


@dataclass
class GuardrailResult:
    """Unified validation result for user input."""
    is_allowed: bool
    intent: QueryIntent
    message: Optional[str] = None
    sanitized_query: str = ""
    detected_pii: List[str] = field(default_factory=list)


class InputGuardrails:
    """Comprehensive input inspection pipeline enforcing privacy and regulatory compliance."""

    def __init__(
        self,
        pii_filter: Optional[PIIFilter] = None,
        intent_classifier: Optional[IntentClassifier] = None,
    ):
        """Initialize unified input guardrails."""
        self.pii_filter = pii_filter or PIIFilter()
        self.intent_classifier = intent_classifier or IntentClassifier()

    def validate(self, query: str) -> GuardrailResult:
        """Execute end-to-end input guardrails: PII Check -> Intent Policy Routing.
        
        Args:
            query: Raw user query string.
            
        Returns:
            GuardrailResult with pass/fail status and compliant response if blocked.
        """
        # Step 1: Scan for personal financial identifiers (PII)
        pii_result = self.pii_filter.check(query)
        if not pii_result.is_safe:
            return GuardrailResult(
                is_allowed=False,
                intent=QueryIntent.PII_VIOLATION,
                message=pii_result.warning_message or PII_SECURITY_WARNING,
                sanitized_query=pii_result.sanitized_text,
                detected_pii=pii_result.detected_types,
            )

        # Step 2: Route intent according to regulatory policies
        decision = self.intent_classifier.route_query(query)
        if not decision.is_allowed_for_rag:
            return GuardrailResult(
                is_allowed=False,
                intent=decision.intent,
                message=decision.refusal_message,
                sanitized_query=query,
                detected_pii=[],
            )

        # Step 3: Input is safe and permitted for RAG retrieval
        return GuardrailResult(
            is_allowed=True,
            intent=QueryIntent.FACTUAL,
            message=None,
            sanitized_query=query,
            detected_pii=[],
        )
