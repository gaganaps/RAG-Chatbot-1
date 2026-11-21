"""Output guardrails enforcing sentence length, single verified citation, and recency line constraints."""

from dataclasses import dataclass, field
import logging
import re
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse

from src.config import (
    ALLOWED_CITATION_DOMAINS,
    AMFI_INVESTOR_EDUCATION_URL,
    MAX_CITATION_LINKS,
    MAX_RESPONSE_SENTENCES,
    RECENCY_FOOTER_PREFIX,
)

logger = logging.getLogger(__name__)


@dataclass
class OutputGuardrailResult:
    """Result of programmatic output compliance enforcement."""
    is_valid: bool
    cleaned_output: str
    body_text: str
    sentence_count: int
    citation_url: str
    recency_date: str
    modifications: List[str] = field(default_factory=list)


class OutputGuardrails:
    """Programmatic post-processor enforcing regulatory and formatting constraints on LLM outputs."""

    # Titles and honorifics that always precede a capitalized proper name
    TITLES = [
        r"Mr\.",
        r"Ms\.",
        r"Mrs\.",
        r"Dr\.",
        r"Prof\.",
        r"Shri\.",
        r"Smt\.",
    ]

    # Currency and financial units that precede or follow numbers
    CURRENCIES = [
        r"Rs\.",
        r"INR\.",
    ]

    # Internal abbreviations that only abbreviate when followed by punctuation, lowercase, or digits
    INTERNAL_ABBREVIATIONS = [
        r"i\.e\.",
        r"e\.g\.",
        r"etc\.",
        r"vs\.",
        r"approx\.",
        r"est\.",
        r"p\.a\.",
        r"a\.m\.",
        r"p\.m\.",
        r"Cr\.",
        r"Lakh\.",
        r"No\.",
        r"Jan\.",
        r"Feb\.",
        r"Mar\.",
        r"Apr\.",
        r"Jun\.",
        r"Jul\.",
        r"Aug\.",
        r"Sep\.",
        r"Sept\.",
        r"Oct\.",
        r"Nov\.",
        r"Dec\.",
    ]

    def __init__(
        self,
        max_sentences: int = MAX_RESPONSE_SENTENCES,
        allowed_domains: Optional[List[str]] = None,
        recency_prefix: str = RECENCY_FOOTER_PREFIX,
    ):
        """Initialize output guardrails.
        
        Args:
            max_sentences: Maximum allowed grammatically complete sentences (default: 3).
            allowed_domains: Whitelist of allowed citation hostnames.
            recency_prefix: Canonical prefix for recency line.
        """
        self.max_sentences = max_sentences
        self.allowed_domains = set(d.lower() for d in (allowed_domains or ALLOWED_CITATION_DOMAINS))
        self.recency_prefix = recency_prefix

    def is_domain_allowed(self, url: str) -> bool:
        """Check whether a URL belongs to the approved domain whitelist."""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            if not netloc:
                return False
            # Strip port if present
            host = netloc.split(":")[0]
            # Match domain or subdomain
            return any(host == d or host.endswith("." + d) for d in self.allowed_domains)
        except Exception:
            return False

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences while protecting decimals, abbreviations, and financial terms.
        
        Args:
            text: Raw input text body.
            
        Returns:
            List of clean, complete sentence strings.
        """
        if not text or not text.strip():
            return []

        cleaned = text.strip()

        # Step 1: Protect decimal numbers (e.g., 0.75%, 12.5) with temporary placeholder
        def replace_decimal(match):
            return match.group(1) + "__DECIMAL_DOT__" + match.group(2)

        cleaned = re.sub(r"(\d+)\.(\d+)", replace_decimal, cleaned)

        # Step 2: Protect titles (e.g., Mr. Gopal Agrawal)
        for i, title in enumerate(self.TITLES):
            pattern = r"(?i:\b" + title + r")"
            placeholder = f"__TITLE_{i}__"
            cleaned = re.sub(pattern, placeholder, cleaned)

        # Step 3: Protect currencies (e.g., Rs. 500)
        for i, curr in enumerate(self.CURRENCIES):
            pattern = r"(?i:\b" + curr + r")"
            placeholder = f"__CURR_{i}__"
            cleaned = re.sub(pattern, placeholder, cleaned)

        # Step 4: Protect internal abbreviations (e.g. 'approx. 12%', 'i.e. annual')
        # Note: Do NOT use global re.IGNORECASE here so [a-z] only matches lowercase (not uppercase sentence starts)
        for i, abbr in enumerate(self.INTERNAL_ABBREVIATIONS):
            pat = r"(?i:\b" + abbr + r")(?=\s*[,;)\]]|\s+[a-z0-9₹%])"
            placeholder = f"__INTABBR_{i}__"
            cleaned = re.sub(pat, placeholder, cleaned)

        # Step 5: Split on true sentence boundaries (. ! ?) followed by whitespace or end of string
        raw_splits = re.split(r"(?<=[.!?])\s+", cleaned)

        # Step 6: Restore placeholders and sanitize
        sentences: List[str] = []
        for s in raw_splits:
            s_clean = s.strip()
            if not s_clean:
                continue

            # Restore titles
            for i, title in enumerate(self.TITLES):
                actual = title.replace(r"\.", ".")
                s_clean = s_clean.replace(f"__TITLE_{i}__", actual)

            # Restore currencies
            for i, curr in enumerate(self.CURRENCIES):
                actual = curr.replace(r"\.", ".")
                s_clean = s_clean.replace(f"__CURR_{i}__", actual)

            # Restore internal abbreviations
            for i, abbr in enumerate(self.INTERNAL_ABBREVIATIONS):
                actual = abbr.replace(r"\.", ".")
                s_clean = s_clean.replace(f"__INTABBR_{i}__", actual)

            # Restore decimal dots
            s_clean = s_clean.replace("__DECIMAL_DOT__", ".")

            # Filter out non-sentences or isolated punctuation
            if len(re.sub(r"[^a-zA-Z0-9]", "", s_clean)) > 0:
                sentences.append(s_clean)

        return sentences

    def enforce(
        self,
        raw_output: str,
        verified_url: Optional[str] = None,
        verified_date: Optional[str] = None,
    ) -> OutputGuardrailResult:
        """Enforce all regulatory output invariants: <= 3 sentences, 1 whitelisted URL, and recency line.
        
        Args:
            raw_output: Raw text output from LLM or template.
            verified_url: Official verified scheme URL from chunk metadata.
            verified_date: Official crawl date from chunk metadata (e.g. "2026-11-15").
            
        Returns:
            OutputGuardrailResult with sanitized and compliant output.
        """
        modifications: List[str] = []
        target_date = verified_date or "2026-11-15"
        fallback_url = verified_url or AMFI_INVESTOR_EDUCATION_URL

        # ----------------------------------------------------------------------
        # 1. Extract and Normalize Recency Line
        # ----------------------------------------------------------------------
        recency_pattern = re.compile(
            r"(?:Last updated from sources|Last updated|Updated as of|Last scraped date):\s*(\d{4}-\d{2}-\d{2})?",
            re.IGNORECASE,
        )

        detected_recency = recency_pattern.search(raw_output)
        if detected_recency:
            found_date = detected_recency.group(1)
            if found_date and found_date != target_date:
                modifications.append(f"Overrode hallucinated date '{found_date}' with verified date '{target_date}'.")
            # Strip recency line from text to isolate answer body
            text_without_recency = recency_pattern.sub("", raw_output).strip()
        else:
            modifications.append(f"Appended missing mandatory recency footer with date '{target_date}'.")
            text_without_recency = raw_output.strip()

        # ----------------------------------------------------------------------
        # 2. Extract and Validate URLs against Domain Whitelist
        # ----------------------------------------------------------------------
        url_pattern = re.compile(r"https?://[^\s)\]\"'>]+", re.IGNORECASE)
        found_raw_urls = url_pattern.findall(text_without_recency)
        
        # Clean trailing punctuation from detected URLs
        clean_found_urls: List[str] = []
        for u in found_raw_urls:
            u_clean = re.sub(r"[.,;!?]+$", "", u)
            clean_found_urls.append(u_clean)

        # Check domain whitelist for all found URLs
        whitelisted_urls: List[str] = []
        for u in clean_found_urls:
            if self.is_domain_allowed(u):
                if u not in whitelisted_urls:
                    whitelisted_urls.append(u)
            else:
                modifications.append(f"Stripped unauthorized non-whitelisted URL: '{u}'.")

        # Determine the single valid citation URL
        if verified_url and self.is_domain_allowed(verified_url):
            citation_url = verified_url
        elif whitelisted_urls:
            citation_url = whitelisted_urls[0]
        else:
            citation_url = fallback_url
            modifications.append(f"Injected fallback compliant citation URL: '{citation_url}'.")

        # Strip explicit "Source: ..." lines and raw URLs from the body text
        text_without_sources = re.sub(r"(?i)\bSource:\s*https?://\S+", "", text_without_recency)
        for u in clean_found_urls:
            text_without_sources = text_without_sources.replace(u, "")

        # Clean multiple blank lines and stray label fragments
        text_body_clean = re.sub(r"(?i)\bSource:\s*$", "", text_without_sources, flags=re.MULTILINE)
        text_body_clean = re.sub(r"\n\s*\n+", "\n", text_body_clean).strip()

        # ----------------------------------------------------------------------
        # 3. Sentence Tokenization & Strict <= 3 Sentence Truncation
        # ----------------------------------------------------------------------
        sentences = self.split_sentences(text_body_clean)
        orig_count = len(sentences)

        if orig_count > self.max_sentences:
            sentences = sentences[: self.max_sentences]
            modifications.append(
                f"Truncated response length from {orig_count} to {self.max_sentences} sentences."
            )

        # Ensure the final sentence terminates cleanly with valid punctuation
        if sentences:
            last_sentence = sentences[-1].strip()
            if not last_sentence.endswith((".", "!", "?")):
                sentences[-1] = last_sentence + "."
                modifications.append("Appended missing terminal period to truncated sentence.")

        final_body = " ".join(sentences).strip()

        # If body was completely empty, provide fallback
        if not final_body:
            final_body = "The requested detail is not found in official scheme records."
            modifications.append("Injected fallback body text due to empty input.")

        # ----------------------------------------------------------------------
        # 4. Final Assembled Output Construction
        # ----------------------------------------------------------------------
        cleaned_output = (
            f"{final_body}\n\n"
            f"Source: {citation_url}\n"
            f"{self.recency_prefix} {target_date}"
        )

        return OutputGuardrailResult(
            is_valid=True,
            cleaned_output=cleaned_output,
            body_text=final_body,
            sentence_count=len(sentences),
            citation_url=citation_url,
            recency_date=target_date,
            modifications=modifications,
        )
