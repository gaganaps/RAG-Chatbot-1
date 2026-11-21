"""High-precision deterministic PII detection, redaction, and security guardrail."""

from dataclasses import dataclass, field
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Standard regulatory refusal for user credential / identifier submission
PII_SECURITY_WARNING = (
    "For your security and privacy, please do not share personal financial identifiers "
    "or credentials (such as PAN, Aadhaar, bank account details, folio numbers, phone numbers, or emails). "
    "I can only assist with public, facts-only mutual fund inquiries."
)


@dataclass
class PIICheckResult:
    """Outcome of PII inspection."""
    is_safe: bool
    detected_types: List[str] = field(default_factory=list)
    sanitized_text: str = ""
    warning_message: Optional[str] = None


class PIIFilter:
    """Deterministic PII scanner for Indian financial and personal identifiers."""

    # Precise compiled regular expressions
    PATTERNS: Dict[str, re.Pattern] = {
        # Indian Permanent Account Number (PAN): 5 uppercase letters, 4 digits, 1 uppercase letter
        "PAN": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b"),
        # Explicit Contextual Folio or Account Number (including formats with slashes like 1234567/89)
        "FOLIO_OR_ACCOUNT": re.compile(r"(?:\bfolio\b|\baccount\b|\bacc\b)(?:[^\d\n]{1,30})?(\b\d+[\/\-]\d+\b|\b\d{7,18}\b)|\b\d{13,18}\b", re.IGNORECASE),
        # Indian Aadhaar Number: 12 digits, cannot start with 0 or 1, optional 4-digit space separation
        "AADHAAR": re.compile(r"\b[2-9]{1}[0-9]{3}\s[0-9]{4}\s[0-9]{4}\b|\b(?:aadhaar|uidai)\b.*?\b[2-9]\d{11}\b|\b[2-9]\d{11}\b", re.IGNORECASE),
        # Indian Mobile Phone Numbers: +91, 91, or 0 prefix followed by 10 digits starting with 6-9
        # (uses negative lookaround so 12+ digit numbers don't falsely match as phone numbers)
        "PHONE": re.compile(r"(?<!\d)(?:(?:\+91|91|0)[\-\s]?)?[6-9]\d{9}(?!\d)"),
        # RFC 5322 compatible email address
        "EMAIL": re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
        # Fallback Generic Account/Folio: 9 to 12 consecutive digits if not caught by Aadhaar/Phone
        "GENERIC_ACCOUNT": re.compile(r"\b\d{9,12}\b"),
    }

    def __init__(self, reject_on_detection: bool = True):
        """Initialize PII filter.
        
        Args:
            reject_on_detection: If True, flags is_safe=False on any PII match.
        """
        self.reject_on_detection = reject_on_detection

    def check(self, text: str) -> PIICheckResult:
        """Scan input query for any personal identifiers or sensitive financial numbers.
        
        Args:
            text: Raw user query string.
            
        Returns:
            PIICheckResult specifying safety status, detected categories, and sanitized text.
        """
        if not text or not text.strip():
            return PIICheckResult(is_safe=True, sanitized_text=text)

        detected_types: List[str] = []
        sanitized_text = text

        for pii_type, pattern in self.PATTERNS.items():
            matches = pattern.findall(sanitized_text)
            if matches:
                detected_types.append(pii_type)
                # Redact each occurrence with a structured token placeholder
                sanitized_text = pattern.sub(f"<{pii_type}_REDACTED>", sanitized_text)

        is_safe = len(detected_types) == 0
        warning = None
        if not is_safe:
            logger.warning(f"PII Guardrail triggered! Detected types: {detected_types}")
            warning = PII_SECURITY_WARNING

        return PIICheckResult(
            is_safe=is_safe if self.reject_on_detection else True,
            detected_types=detected_types,
            sanitized_text=sanitized_text,
            warning_message=warning,
        )

    def scrub(self, text: str) -> str:
        """Utility method to sanitize PII without blocking."""
        result = self.check(text)
        return result.sanitized_text
