"""Centralized configuration for the Mutual Fund FAQ Assistant."""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
CHROMA_PERSIST_DIR = PROJECT_ROOT / "chroma_db"

# Ensure runtime directories exist
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SchemeConfig:
    """Configuration definition for an indexed mutual fund scheme."""
    scheme_id: str
    scheme_name: str
    category: str
    amc: str
    groww_url: str


# Phase 1: Curated 5 HDFC Mutual Fund Scheme URLs on Groww
ACTIVE_SCHEMES: Dict[str, SchemeConfig] = {
    "hdfc-flexi-cap": SchemeConfig(
        scheme_id="hdfc-flexi-cap",
        scheme_name="HDFC Flexi Cap Fund Direct-Growth",
        category="Equity: Flexi Cap",
        amc="HDFC Mutual Fund",
        groww_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    ),
    "hdfc-silver-etf-fof": SchemeConfig(
        scheme_id="hdfc-silver-etf-fof",
        scheme_name="HDFC Silver ETF FoF Direct-Growth",
        category="Commodities: Silver FoF",
        amc="HDFC Mutual Fund",
        groww_url="https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth",
    ),
    "hdfc-balanced-advantage": SchemeConfig(
        scheme_id="hdfc-balanced-advantage",
        scheme_name="HDFC Balanced Advantage Fund Direct-Growth",
        category="Hybrid: Dynamic Asset Allocation",
        amc="HDFC Mutual Fund",
        groww_url="https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth",
    ),
    "hdfc-large-and-mid-cap": SchemeConfig(
        scheme_id="hdfc-large-and-mid-cap",
        scheme_name="HDFC Large and Mid Cap Fund Direct-Growth",
        category="Equity: Large & Mid Cap",
        amc="HDFC Mutual Fund",
        groww_url="https://groww.in/mutual-funds/hdfc-large-mid-cap-fund-direct-growth",
    ),
    "hdfc-manufacturing": SchemeConfig(
        scheme_id="hdfc-manufacturing",
        scheme_name="HDFC Manufacturing Fund Direct-Growth",
        category="Equity: Thematic / Sectoral",
        amc="HDFC Mutual Fund",
        groww_url="https://groww.in/mutual-funds/hdfc-manufacturing-fund-direct-growth",
    ),
}

# Embeddings & Vector Store Configuration
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "hdfc_mutual_funds")

# Free LLM Configuration (Default: Groq openai/gpt-oss-120b or qwen/qwen3.8-27b)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Secondary Fallback: Google Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Regulatory & Guardrail Constraints
MANDATORY_DISCLAIMER = "Facts-only. No investment advice."
MAX_RESPONSE_SENTENCES = 3
MAX_CITATION_LINKS = 1
RECENCY_FOOTER_PREFIX = "Last updated from sources:"
SIMILARITY_CONFIDENCE_THRESHOLD = 0.65

# Domain Whitelist for Citations
ALLOWED_CITATION_DOMAINS: List[str] = [
    "groww.in",
    "hdfcfund.com",
    "amfiindia.com",
    "sebi.gov.in",
]

# Educational Resource Link for Refusals
AMFI_INVESTOR_EDUCATION_URL = "https://www.amfiindia.com/investor-corner/knowledge-center"
SEBI_INVESTOR_PORTAL_URL = "https://investor.sebi.gov.in"

# Daily Ingestion Scheduler Configuration (Target: 10:00 AM IST Daily)
SCHEDULER_HOUR: int = int(os.getenv("SCHEDULER_HOUR", os.getenv("INGESTION_SCHEDULE_HOUR", "10")))
SCHEDULER_MINUTE: int = int(os.getenv("SCHEDULER_MINUTE", os.getenv("INGESTION_SCHEDULE_MINUTE", "0")))
SCHEDULER_TIMEZONE: str = os.getenv("SCHEDULER_TIMEZONE", "Asia/Kolkata")

