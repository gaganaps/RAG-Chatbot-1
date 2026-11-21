"""Baseline scaffolding and environment verification tests (Phase 0)."""

import importlib
from pathlib import Path
import pytest

from src.config import (
    ACTIVE_SCHEMES,
    ALLOWED_CITATION_DOMAINS,
    DATA_PROCESSED_DIR,
    DATA_RAW_DIR,
    MANDATORY_DISCLAIMER,
    MAX_CITATION_LINKS,
    MAX_RESPONSE_SENTENCES,
    PROJECT_ROOT,
)


def test_subpackages_are_importable():
    """Verify that all core architectural subpackages can be imported."""
    packages = [
        "src",
        "src.ingestion",
        "src.retrieval",
        "src.guardrails",
        "src.pipeline",
        "src.ui",
        "src.config",
    ]
    for pkg in packages:
        mod = importlib.import_module(pkg)
        assert mod is not None, f"Failed to import package: {pkg}"


def test_directory_scaffolding():
    """Verify that required project directories exist."""
    assert PROJECT_ROOT.exists(), "Project root does not exist."
    assert (PROJECT_ROOT / "docs").exists(), "docs directory is missing."
    assert DATA_RAW_DIR.exists(), "data/raw directory is missing."
    assert DATA_PROCESSED_DIR.exists(), "data/processed directory is missing."


def test_active_schemes_configuration():
    """Verify the 5 active Groww scheme URLs are properly configured."""
    assert len(ACTIVE_SCHEMES) == 5, f"Expected 5 active schemes, found {len(ACTIVE_SCHEMES)}"

    expected_slugs = [
        "hdfc-flexi-cap",
        "hdfc-silver-etf-fof",
        "hdfc-balanced-advantage",
        "hdfc-large-and-mid-cap",
        "hdfc-manufacturing",
    ]
    for slug in expected_slugs:
        assert slug in ACTIVE_SCHEMES, f"Missing expected scheme slug: {slug}"
        scheme = ACTIVE_SCHEMES[slug]
        assert scheme.amc == "HDFC Mutual Fund"
        assert scheme.groww_url.startswith("https://groww.in/mutual-funds/")


def test_regulatory_constraints_configuration():
    """Verify core regulatory and guardrail parameters match problemStatement.md."""
    assert MANDATORY_DISCLAIMER == "Facts-only. No investment advice."
    assert MAX_RESPONSE_SENTENCES == 3
    assert MAX_CITATION_LINKS == 1
    assert "groww.in" in ALLOWED_CITATION_DOMAINS
    assert "hdfcfund.com" in ALLOWED_CITATION_DOMAINS
    assert "amfiindia.com" in ALLOWED_CITATION_DOMAINS
    assert "sebi.gov.in" in ALLOWED_CITATION_DOMAINS
