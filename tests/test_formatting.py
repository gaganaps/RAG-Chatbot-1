"""Unit and edge-case test suite for Phase 6: Output Guardrails & Compliance Validation."""

import pytest

from src.config import (
    ALLOWED_CITATION_DOMAINS,
    AMFI_INVESTOR_EDUCATION_URL,
    RECENCY_FOOTER_PREFIX,
)
from src.guardrails.output_guard import OutputGuardrails, OutputGuardrailResult
from src.pipeline.rag_engine import RAGEngine, RAGResponse


@pytest.fixture(scope="module")
def output_guard() -> OutputGuardrails:
    """Shared OutputGuardrails fixture."""
    return OutputGuardrails()


# ==============================================================================
# 1. Sentence Tokenization & Abbreviation Protection Tests (EC-OUT-01, EC-OUT-02, TC-EC-09)
# ==============================================================================

def test_sentence_split_protects_currency_and_decimals(output_guard: OutputGuardrails):
    """TC-EC-09 & EC-OUT-01: Protect 'Rs.' and percentage decimals ('0.75%') from false splitting."""
    text = "The minimum investment is Rs. 500. The TER is 0.75% inclusive of GST. The exit load is Nil."
    sentences = output_guard.split_sentences(text)
    assert len(sentences) == 3
    assert sentences[0] == "The minimum investment is Rs. 500."
    assert sentences[1] == "The TER is 0.75% inclusive of GST."
    assert sentences[2] == "The exit load is Nil."


def test_sentence_split_protects_honorifics_and_titles(output_guard: OutputGuardrails):
    """EC-OUT-02: Protect honorific titles ('Mr.', 'Ms.', 'Dr.') from false sentence splits."""
    text = "The fund is managed by Mr. Gopal Agrawal. He has over 20 years experience."
    sentences = output_guard.split_sentences(text)
    assert len(sentences) == 2
    assert sentences[0] == "The fund is managed by Mr. Gopal Agrawal."
    assert sentences[1] == "He has over 20 years experience."


def test_sentence_split_protects_latin_and_general_abbreviations(output_guard: OutputGuardrails):
    """Protect abbreviations like 'i.e.', 'e.g.', 'etc.', and 'p.a.'."""
    text = "The returns (i.e. annual growth) are approx. 12% p.a. However, exit load applies etc. Always check terms."
    sentences = output_guard.split_sentences(text)
    assert len(sentences) == 3


# ==============================================================================
# 2. Sentence Length Enforcement (<= 3 Sentences) (EC-OUT-03, EC-OUT-04, TC-EC-07)
# ==============================================================================

def test_truncates_long_output_to_three_sentences(output_guard: OutputGuardrails):
    """TC-EC-07 & EC-OUT-03: Raw output with 5 sentences is strictly sliced to the first 3."""
    raw_output = (
        "Sentence one explains the expense ratio. "
        "Sentence two details the fund manager tenure. "
        "Sentence three specifies the minimum SIP amount. "
        "Sentence four provides additional commentary that must be stripped. "
        "Sentence five is extraneous advice that violates length limits.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth\n"
        "Last updated from sources: 2026-11-15"
    )

    result: OutputGuardrailResult = output_guard.enforce(
        raw_output=raw_output,
        verified_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
        verified_date="2026-11-15",
    )

    assert result.is_valid
    assert result.sentence_count == 3
    assert "Sentence one" in result.body_text
    assert "Sentence two" in result.body_text
    assert "Sentence three" in result.body_text
    assert "Sentence four" not in result.body_text
    assert "Sentence five" not in result.body_text
    assert any("Truncated" in m for m in result.modifications)


def test_ensures_terminal_punctuation_on_fragment_truncation(output_guard: OutputGuardrails):
    """EC-OUT-04: Ensure the last sentence ends with terminal punctuation (. ! ?)."""
    raw_output = "First sentence here. Second sentence here. Third sentence lacks period"
    result: OutputGuardrailResult = output_guard.enforce(raw_output)
    assert result.body_text.endswith(".")
    assert result.sentence_count == 3


# ==============================================================================
# 3. Citation Whitelist & Single-Link Enforcement (EC-OUT-05, EC-OUT-06, TC-EC-08)
# ==============================================================================

def test_domain_whitelist_validation(output_guard: OutputGuardrails):
    """Verify whitelist validation accepts allowed domains and rejects unauthorized hosts."""
    assert output_guard.is_domain_allowed("https://groww.in/mutual-funds/test")
    assert output_guard.is_domain_allowed("https://www.hdfcfund.com/nav")
    assert output_guard.is_domain_allowed("https://www.amfiindia.com/investor-corner")
    assert output_guard.is_domain_allowed("https://investor.sebi.gov.in")

    # Unauthorized domains
    assert not output_guard.is_domain_allowed("https://moneycontrol.com/nav")
    assert not output_guard.is_domain_allowed("https://valueresearchonline.com/funds")
    assert not output_guard.is_domain_allowed("https://phishing-site.org/hdfc")


def test_strips_unauthorized_third_party_url(output_guard: OutputGuardrails):
    """EC-OUT-05: Unauthorized third-party URL is stripped and replaced with verified Groww URL."""
    raw_output = (
        "The expense ratio is 0.85% according to https://moneycontrol.com/mutual-funds/hdfc.\n\n"
        "Source: https://moneycontrol.com/mutual-funds/hdfc\n"
        "Last updated from sources: 2026-11-15"
    )

    verified_url = "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"
    result = output_guard.enforce(raw_output, verified_url=verified_url)

    assert result.citation_url == verified_url
    assert "moneycontrol.com" not in result.cleaned_output
    assert any("Stripped unauthorized" in m for m in result.modifications)


def test_enforces_strictly_one_citation_link(output_guard: OutputGuardrails):
    """TC-EC-08 & EC-OUT-06: Multiple URLs in output are collapsed to exactly one citation link."""
    raw_output = (
        "Check Groww at https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth or "
        "AMFI at https://www.amfiindia.com for details.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth\n"
        "Last updated from sources: 2026-11-15"
    )

    result = output_guard.enforce(
        raw_output=raw_output,
        verified_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    )

    # Check that in cleaned_output there is only one "https://" link
    import re
    urls = re.findall(r"https?://[^\s]+", result.cleaned_output)
    assert len(urls) == 1
    assert urls[0] == "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"


# ==============================================================================
# 4. Mandatory Recency Line Verification (EC-OUT-07, EC-OUT-08)
# ==============================================================================

def test_appends_missing_recency_footer(output_guard: OutputGuardrails):
    """EC-OUT-07: Append mandatory recency footer when omitted by LLM."""
    raw_output = (
        "The expense ratio is 0.85%.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"
    )

    result = output_guard.enforce(
        raw_output=raw_output,
        verified_date="2026-11-15",
    )

    assert f"{RECENCY_FOOTER_PREFIX} 2026-11-15" in result.cleaned_output
    assert any("Appended missing mandatory recency footer" in m for m in result.modifications)


def test_overrides_hallucinated_recency_date(output_guard: OutputGuardrails):
    """EC-OUT-08: Override hallucinated future/invalid recency date with official metadata date."""
    raw_output = (
        "The exit load is 1% within 1 year.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth\n"
        "Last updated from sources: 2026-12-31"  # Hallucinated future date
    )

    result = output_guard.enforce(
        raw_output=raw_output,
        verified_date="2026-11-15",
    )

    assert "2026-12-31" not in result.cleaned_output
    assert f"{RECENCY_FOOTER_PREFIX} 2026-11-15" in result.cleaned_output
    assert any("Overrode hallucinated date" in m for m in result.modifications)


# ==============================================================================
# 5. End-to-End Pipeline Output Compliance Verification
# ==============================================================================

def test_rag_engine_output_strictly_compliant():
    """Verify that RAGEngine answers always satisfy sentence count <= 3, single URL, and recency line."""
    engine = RAGEngine()
    resp: RAGResponse = engine.answer("What is the expense ratio and exit load of HDFC Flexi Cap Fund?")

    assert not resp.is_refusal
    assert not resp.is_fallback

    # Validate output formatting invariants
    guard = OutputGuardrails()
    sentences = guard.split_sentences(resp.answer.split("\n\nSource:")[0])
    assert len(sentences) <= 3

    # Validate exactly one citation link
    import re
    urls = re.findall(r"https?://[^\s]+", resp.answer)
    assert len(urls) == 1
    assert "groww.in" in urls[0]

    # Validate recency line
    assert f"{RECENCY_FOOTER_PREFIX} 2026-11-15" in resp.answer
