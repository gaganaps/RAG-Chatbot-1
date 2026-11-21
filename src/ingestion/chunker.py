"""Hierarchical semantic chunker with immutable metadata context injection."""

import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.config import DATA_PROCESSED_DIR
from src.ingestion.parser import GrowwParser, ParsedSchemeData

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class CorpusChunk(BaseModel):
    """Schema for a chunk in the processed knowledge base."""
    chunk_id: str
    scheme_id: str
    scheme_name: str
    amc: str
    category: str
    section: str
    source_url: str
    last_scraped_date: str
    text: str
    token_count: int


class SchemeChunker:
    """Chunks parsed scheme data into hierarchical semantic chunks with context headers."""

    def __init__(self, processed_dir: Path = DATA_PROCESSED_DIR):
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_path = self.processed_dir / "corpus.jsonl"
        self.readable_json_path = self.processed_dir / "corpus.json"

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        """Estimate token count based on whitespace and punctuation tokens."""
        return len(re.findall(r"\w+|[^\w\s]", text))

    def _build_header(self, scheme: ParsedSchemeData, section_title: str) -> str:
        """Construct the immutable metadata header prepended to every chunk."""
        sub_cat = f" ({scheme.sub_category})" if scheme.sub_category else ""
        return (
            f"[SCHEME]: {scheme.scheme_name}\n"
            f"[AMC]: {scheme.amc_name}\n"
            f"[CATEGORY]: {scheme.category}{sub_cat}\n"
            f"[SECTION]: {section_title}\n"
            f"[SOURCE_URL]: {scheme.source_url}\n"
            f"[LAST_UPDATED]: {scheme.last_scraped_date}\n"
            f"---\n"
        )

    def chunk_scheme(self, scheme: ParsedSchemeData) -> List[CorpusChunk]:
        """Generate hierarchical chunks for a single mutual fund scheme.
        
        Args:
            scheme: ParsedSchemeData instance.
            
        Returns:
            List of CorpusChunk objects.
        """
        chunks: List[CorpusChunk] = []

        # =====================================================================
        # Tier 1: Targeted Section Chunks (Precision facts)
        # =====================================================================
        section_titles = {
            "expense_ratio": "Expense Ratio & Management Fees",
            "exit_load": "Exit Load & Redemption Terms",
            "investment_limits": "Investment Limits & Minimums (SIP & Lumpsum)",
            "riskometer_and_benchmark": "Riskometer Rating & Benchmark Index",
            "lock_in": "Lock-in Period & Redemption Eligibility",
            "fund_management": "Fund Management Team Overview",
        }

        for section_key, section_text in scheme.section_facts.items():
            section_title = section_titles.get(section_key, section_key.replace("_", " ").title())
            header = self._build_header(scheme, section_title)
            full_text = header + section_text.strip()

            chunks.append(
                CorpusChunk(
                    chunk_id=f"{scheme.scheme_id}_{section_key}",
                    scheme_id=scheme.scheme_id,
                    scheme_name=scheme.scheme_name,
                    amc=scheme.amc_name,
                    category=scheme.category,
                    section=section_key,
                    source_url=scheme.source_url,
                    last_scraped_date=scheme.last_scraped_date,
                    text=full_text,
                    token_count=self._estimate_token_count(full_text),
                )
            )

        # =====================================================================
        # Tier 2: Comprehensive Scheme Overview Chunk
        # =====================================================================
        overview_header = self._build_header(scheme, "Comprehensive Scheme Factsheet Overview")
        overview_body = (
            f"{scheme.scheme_name} is an open-ended mutual fund scheme offered by {scheme.amc_name} "
            f"under the {scheme.category} ({scheme.sub_category or 'General'}) category.\n"
            f"• Total Expense Ratio (Direct Plan): {scheme.expense_ratio}\n"
            f"• Exit Load: {scheme.exit_load}\n"
            f"• Minimum Investment: Minimum SIP is ₹{scheme.min_sip_investment}; Minimum Lumpsum is ₹{scheme.min_lumpsum_investment}.\n"
            f"• Lock-in Period: {scheme.lock_in_period}\n"
            f"• Riskometer: {scheme.riskometer}\n"
            f"• Benchmark: {scheme.benchmark_name}\n"
            f"• Fund Managers: {', '.join(m.person_name for m in scheme.fund_managers) if scheme.fund_managers else 'Not specified'}.\n"
            f"• Source Citation: {scheme.source_url}\n"
            f"• Last updated from sources: {scheme.last_scraped_date}"
        )
        overview_text = overview_header + overview_body.strip()
        chunks.append(
            CorpusChunk(
                chunk_id=f"{scheme.scheme_id}_overview",
                scheme_id=scheme.scheme_id,
                scheme_name=scheme.scheme_name,
                amc=scheme.amc_name,
                category=scheme.category,
                section="overview",
                source_url=scheme.source_url,
                last_scraped_date=scheme.last_scraped_date,
                text=overview_text,
                token_count=self._estimate_token_count(overview_text),
            )
        )

        # =====================================================================
        # Tier 3: Granular Fund Manager Profile Chunks
        # =====================================================================
        # If the scheme has multiple managers, generate dedicated manager profile chunks
        for mgr in scheme.fund_managers:
            mgr_slug = re.sub(r"[^a-zA-Z0-9]+", "-", mgr.person_name.lower()).strip("-")
            mgr_header = self._build_header(scheme, f"Fund Manager Profile: {mgr.person_name}")

            since_text = f"He/She has been managing {scheme.scheme_name} since {mgr.managing_since}." if mgr.managing_since else ""
            edu_text = f"Education & Qualifications: {mgr.education}." if mgr.education else ""
            exp_text = f"Professional Background & Experience: {mgr.experience}." if mgr.experience else ""
            
            other_text = ""
            if mgr.other_funds_managed:
                sample_funds = mgr.other_funds_managed[:5]
                other_text = f"Other key schemes managed at {scheme.amc_name} include: {', '.join(sample_funds)}."

            mgr_body = (
                f"{mgr.person_name} is a designated fund manager for {scheme.scheme_name} at {scheme.amc_name}.\n"
                f"{since_text} {edu_text}\n"
                f"{exp_text}\n"
                f"{other_text}"
            ).strip()

            mgr_text = mgr_header + mgr_body
            chunks.append(
                CorpusChunk(
                    chunk_id=f"{scheme.scheme_id}_manager_{mgr_slug}",
                    scheme_id=scheme.scheme_id,
                    scheme_name=scheme.scheme_name,
                    amc=scheme.amc_name,
                    category=scheme.category,
                    section="fund_management_profile",
                    source_url=scheme.source_url,
                    last_scraped_date=scheme.last_scraped_date,
                    text=mgr_text,
                    token_count=self._estimate_token_count(mgr_text),
                )
            )

        return chunks

    def process_and_save_corpus(
        self,
        schemes: Dict[str, ParsedSchemeData],
    ) -> List[CorpusChunk]:
        """Chunk all parsed schemes and write to data/processed/corpus.jsonl.
        
        Args:
            schemes: Dict mapping scheme_id to ParsedSchemeData.
            
        Returns:
            List of all generated CorpusChunk objects.
        """
        all_chunks: List[CorpusChunk] = []

        for scheme_id, scheme in schemes.items():
            scheme_chunks = self.chunk_scheme(scheme)
            all_chunks.extend(scheme_chunks)
            logger.info(f"Generated {len(scheme_chunks)} chunks for '{scheme_id}'")

        # 1. Write compact streaming format (JSONL)
        with open(self.corpus_path, "w", encoding="utf-8") as f:
            for chunk in all_chunks:
                f.write(chunk.model_dump_json() + "\n")

        # 2. Write human-readable formatted JSON (indent=2)
        with open(self.readable_json_path, "w", encoding="utf-8") as f:
            json.dump([chunk.model_dump() for chunk in all_chunks], f, indent=2, ensure_ascii=False)

        logger.info(
            f"Successfully compiled knowledge corpus: {len(all_chunks)} chunks written to {self.corpus_path} and {self.readable_json_path}"
        )
        return all_chunks

    def load_corpus(self) -> List[CorpusChunk]:
        """Load compiled corpus chunks from data/processed/corpus.jsonl."""
        if not self.corpus_path.exists():
            raise FileNotFoundError(f"Corpus file not found at: {self.corpus_path}")

        chunks: List[CorpusChunk] = []
        with open(self.corpus_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(CorpusChunk.model_validate_json(line))
        return chunks


if __name__ == "__main__":
    parser = GrowwParser()
    schemes = parser.parse_all_cached()
    chunker = SchemeChunker()
    chunks = chunker.process_and_save_corpus(schemes)
    print(f"\nCorpus generation complete: {len(chunks)} total chunks.")
    print("\nSample Chunk Preview:")
    print(chunks[0].text)
