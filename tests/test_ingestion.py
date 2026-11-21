"""Comprehensive unit tests for Phase 1 (Scraper, Parser, Chunker, Scheduler)."""

import json
from pathlib import Path
import pytest

from src.config import ACTIVE_SCHEMES, DATA_PROCESSED_DIR, DATA_RAW_DIR
from src.ingestion.chunker import CorpusChunk, SchemeChunker
from src.ingestion.parser import FundManager, GrowwParser, ParsedSchemeData
from src.ingestion.scheduler import IngestionScheduler
from src.ingestion.scraper import GrowwScraper


@pytest.fixture
def parser():
    return GrowwParser(raw_dir=DATA_RAW_DIR)


@pytest.fixture
def scraper():
    return GrowwScraper(raw_dir=DATA_RAW_DIR)


@pytest.fixture
def chunker():
    return SchemeChunker(processed_dir=DATA_PROCESSED_DIR)


@pytest.fixture
def scheduler():
    return IngestionScheduler(raw_dir=DATA_RAW_DIR, processed_dir=DATA_PROCESSED_DIR)


# ==============================================================================
# Task 1: Scraper Tests
# ==============================================================================

def test_scraper_cache_files_exist():
    """Verify raw cache files exist for all 5 active schemes."""
    for scheme_id in ACTIVE_SCHEMES:
        json_file = DATA_RAW_DIR / f"{scheme_id}.json"
        html_file = DATA_RAW_DIR / f"{scheme_id}.html"
        assert json_file.exists(), f"Missing cached JSON for {scheme_id}"
        assert html_file.exists(), f"Missing cached HTML for {scheme_id}"
        assert json_file.stat().st_size > 1000, f"JSON file for {scheme_id} is unexpectedly small"
        assert html_file.stat().st_size > 1000, f"HTML file for {scheme_id} is unexpectedly small"


# ==============================================================================
# Task 2: Parser Tests
# ==============================================================================

def test_parser_parses_all_active_schemes(parser):
    """Verify that all 5 schemes are successfully parsed from cache."""
    parsed = parser.parse_all_cached()
    assert len(parsed) == 5, f"Expected 5 parsed schemes, got {len(parsed)}"

    expected_ids = set(ACTIVE_SCHEMES.keys())
    assert set(parsed.keys()) == expected_ids


def test_parser_extracted_fields(parser):
    """Verify specific financial parameters for known schemes."""
    parsed = parser.parse_all_cached()

    # HDFC Flexi Cap checks
    flexi = parsed["hdfc-flexi-cap"]
    assert "Flexi Cap" in flexi.scheme_name
    assert flexi.expense_ratio == "0.74%"
    assert "1% if redeemed within 1 year" in flexi.exit_load
    assert flexi.min_sip_investment == 100
    assert flexi.benchmark_name == "NIFTY 500 Total Return Index"
    assert flexi.riskometer == "Very High Risk"
    assert len(flexi.fund_managers) >= 1
    manager_names = [m.person_name for m in flexi.fund_managers]
    assert "Dhruv Muchhal" in manager_names or "Amit Ganatra" in manager_names

    # HDFC Silver ETF FoF checks
    silver = parsed["hdfc-silver-etf-fof"]
    assert "Silver" in silver.scheme_name
    assert silver.expense_ratio == "0.22%"
    assert "15 days" in silver.exit_load
    assert silver.benchmark_name == "Domestic Price of Silver"
    assert silver.min_sip_investment == 100

    # HDFC Balanced Advantage checks
    baf = parsed["hdfc-balanced-advantage"]
    assert "Balanced Advantage" in baf.scheme_name
    assert baf.expense_ratio == "0.76%"
    assert "15%" in baf.exit_load
    assert len(baf.fund_managers) >= 2


def test_fund_manager_structure(parser):
    """Verify fund manager models have credentials, tenure, and other funds."""
    parsed = parser.parse_all_cached()
    flexi = parsed["hdfc-flexi-cap"]

    for manager in flexi.fund_managers:
        assert isinstance(manager, FundManager)
        assert len(manager.person_name) > 2
        assert manager.education or manager.experience or manager.managing_since


def test_section_facts_dictionary(parser):
    """Verify each parsed scheme has granular section facts for RAG retrieval."""
    parsed = parser.parse_all_cached()
    for scheme in parsed.values():
        facts = scheme.section_facts
        assert "expense_ratio" in facts
        assert "exit_load" in facts
        assert "investment_limits" in facts
        assert "fund_management" in facts
        assert "riskometer_and_benchmark" in facts
        assert "lock_in" in facts
        assert len(scheme.structured_summary) > 100


# ==============================================================================
# Task 3: Chunker Tests
# ==============================================================================

def test_chunker_generates_hierarchical_chunks(parser, chunker):
    """Verify chunk generation across all 5 schemes in both JSONL and formatted JSON."""
    schemes = parser.parse_all_cached()
    chunks = chunker.process_and_save_corpus(schemes)

    # 5 schemes should yield between 40 and 60 high-precision chunks
    assert 40 <= len(chunks) <= 60, f"Expected 40-60 chunks, got {len(chunks)}"

    # Verify JSONL corpus file exists and is populated
    assert chunker.corpus_path.exists()
    assert chunker.corpus_path.stat().st_size > 5000

    # Verify readable formatted JSON file exists and has identical chunk count
    assert chunker.readable_json_path.exists()
    assert chunker.readable_json_path.stat().st_size > 5000
    with open(chunker.readable_json_path, "r", encoding="utf-8") as f:
        formatted_data = json.load(f)
    assert len(formatted_data) == len(chunks)
    assert formatted_data[0]["chunk_id"] == chunks[0].chunk_id


def test_chunk_metadata_headers(chunker):
    """Verify every chunk contains the required immutable metadata header."""
    chunks = chunker.load_corpus()
    for chunk in chunks:
        assert isinstance(chunk, CorpusChunk)
        assert chunk.scheme_id in ACTIVE_SCHEMES
        assert chunk.source_url.startswith("https://groww.in/mutual-funds/")
        assert chunk.token_count > 20
        assert chunk.token_count < 600

        # Header check
        header_lines = [
            f"[SCHEME]: {chunk.scheme_name}",
            f"[AMC]: {chunk.amc}",
            f"[SOURCE_URL]: {chunk.source_url}",
            f"[LAST_UPDATED]: {chunk.last_scraped_date}",
            "---",
        ]
        for h in header_lines:
            assert h in chunk.text, f"Missing header line '{h}' in chunk {chunk.chunk_id}"


def test_chunk_section_coverage(chunker):
    """Verify that every scheme has chunks for each critical factual section."""
    chunks = chunker.load_corpus()
    for scheme_id in ACTIVE_SCHEMES:
        scheme_chunks = [c for c in chunks if c.scheme_id == scheme_id]
        sections = {c.section for c in scheme_chunks}
        assert "expense_ratio" in sections
        assert "fund_size" in sections
        assert "exit_load" in sections
        assert "investment_limits" in sections
        assert "riskometer_and_benchmark" in sections
        assert "lock_in" in sections
        assert "fund_management" in sections
        assert "overview" in sections


# ==============================================================================
# Task 4: Scheduler Tests
# ==============================================================================

def test_scheduler_detects_metric_diffs(scheduler, parser):
    """Verify the scheduler's metric diffing logic."""
    parsed = parser.parse_all_cached()
    old_schemes = parsed
    # Create modified clone to test diff detection
    new_schemes = {k: v.model_copy(deep=True) for k, v in parsed.items()}
    new_schemes["hdfc-flexi-cap"].expense_ratio = "0.85%"
    new_schemes["hdfc-flexi-cap"].min_sip_investment = 500

    diffs = scheduler.detect_metric_diffs(old_schemes, new_schemes)
    assert len(diffs) == 2
    fields = {d["field"] for d in diffs}
    assert "expense_ratio" in fields
    assert "min_sip_investment" in fields


def test_scheduler_pipeline_execution(scheduler):
    """Verify end-to-end scheduler execution with cached data."""
    summary = scheduler.run_ingestion_pipeline(force_refresh=False)
    assert summary["status"] == "SUCCESS"
    assert summary["schemes_processed"] == 5
    assert summary["total_chunks_generated"] >= 45
    assert Path(summary["corpus_file"]).exists()


def test_scheduler_daily_10am_ist_configuration(scheduler):
    """Verify that the daily recurring scheduler is configured for 10:00 AM IST."""
    from datetime import datetime, timezone
    from src.config import SCHEDULER_HOUR, SCHEDULER_MINUTE, SCHEDULER_TIMEZONE

    assert SCHEDULER_HOUR == 10
    assert SCHEDULER_MINUTE == 0
    assert SCHEDULER_TIMEZONE == "Asia/Kolkata"

    # Start non-blocking scheduler instance to inspect registered job
    sched = scheduler.start_scheduler_daemon(
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE,
        timezone_name=SCHEDULER_TIMEZONE,
        blocking=False,
    )
    try:
        job = sched.get_job("daily_mutual_fund_ingestion")
        assert job is not None
        assert job.name == "Daily Groww Mutual Fund Data Refresh"

        # Check next fire time is aligned with Asia/Kolkata (+05:30) at 10:00 AM
        next_fire = job.trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        assert next_fire is not None
        assert next_fire.hour == 10
        assert next_fire.minute == 0
        assert str(next_fire.tzinfo) in ("Asia/Kolkata", "+05:30")
    finally:
        sched.shutdown(wait=False)

