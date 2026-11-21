"""Daily automated scheduler for recurring mutual fund ingestion and corpus refresh."""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import (
    DATA_PROCESSED_DIR,
    DATA_RAW_DIR,
    SCHEDULER_HOUR,
    SCHEDULER_MINUTE,
    SCHEDULER_TIMEZONE,
)
from src.ingestion.chunker import CorpusChunk, SchemeChunker
from src.ingestion.parser import GrowwParser, ParsedSchemeData
from src.ingestion.scraper import GrowwScraper

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class IngestionScheduler:
    """Automates daily scraping, metric diffing, and corpus re-indexing."""

    def __init__(
        self,
        raw_dir: Path = DATA_RAW_DIR,
        processed_dir: Path = DATA_PROCESSED_DIR,
    ):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.scraper = GrowwScraper(raw_dir=self.raw_dir)
        self.parser = GrowwParser(raw_dir=self.raw_dir)
        self.chunker = SchemeChunker(processed_dir=self.processed_dir)

    def detect_metric_diffs(
        self,
        old_schemes: Dict[str, ParsedSchemeData],
        new_schemes: Dict[str, ParsedSchemeData],
    ) -> List[Dict[str, Any]]:
        """Compare previously parsed scheme data with new data to log parameter diffs.
        
        Args:
            old_schemes: Mapping of scheme_id to previous ParsedSchemeData.
            new_schemes: Mapping of scheme_id to fresh ParsedSchemeData.
            
        Returns:
            List of detected changes with scheme_id, field, old_val, and new_val.
        """
        diffs: List[Dict[str, Any]] = []
        fields_to_compare = [
            "expense_ratio",
            "exit_load",
            "min_sip_investment",
            "min_lumpsum_investment",
            "riskometer",
            "benchmark_name",
        ]

        for scheme_id, new_data in new_schemes.items():
            if scheme_id not in old_schemes:
                diffs.append({
                    "scheme_id": scheme_id,
                    "field": "scheme",
                    "action": "added",
                })
                continue

            old_data = old_schemes[scheme_id]
            for field in fields_to_compare:
                old_val = getattr(old_data, field, None)
                new_val = getattr(new_data, field, None)
                if old_val != new_val:
                    diffs.append({
                        "scheme_id": scheme_id,
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val,
                    })

            # Compare fund manager names
            old_mgrs = {m.person_name for m in old_data.fund_managers}
            new_mgrs = {m.person_name for m in new_data.fund_managers}
            if old_mgrs != new_mgrs:
                diffs.append({
                    "scheme_id": scheme_id,
                    "field": "fund_managers",
                    "old_value": list(old_mgrs),
                    "new_value": list(new_mgrs),
                })

        return diffs

    def run_ingestion_pipeline(
        self,
        force_refresh: bool = False,
        sync_vector_index: bool = True,
    ) -> Dict[str, Any]:
        """Execute one end-to-end cycle: Scrape -> Parse -> Diff -> Chunk -> Save -> Index.
        
        Args:
            force_refresh: If True, bypasses cache and re-crawls all live Groww URLs.
            sync_vector_index: If True, upserts chunks directly into persistent ChromaDB index.
            
        Returns:
            Execution summary dictionary.
        """
        start_time = time.time()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"=== Starting Ingestion Pipeline Execution at {now_str} ===")

        # 1. Load existing parsed state for diff comparison
        old_schemes: Dict[str, ParsedSchemeData] = {}
        try:
            old_schemes = self.parser.parse_all_cached()
        except Exception as e:
            logger.info(f"No prior parsed state available for diff comparison: {e}")

        # 2. Scrape target Groww URLs
        logger.info("Step 1/4: Scraping active Groww scheme URLs...")
        scraped_payloads = self.scraper.scrape_all_active_schemes(force_refresh=force_refresh)

        # 3. Parse extracted data into structured models
        logger.info("Step 2/4: Parsing financial parameters & fund managers...")
        new_schemes: Dict[str, ParsedSchemeData] = {}
        for scheme_id, raw_payload in scraped_payloads.items():
            parsed = self.parser.parse_raw_payload(raw_payload)
            new_schemes[scheme_id] = parsed

        # 4. Check for metric diffs
        diffs = self.detect_metric_diffs(old_schemes, new_schemes)
        if diffs:
            logger.info(f"Detected {len(diffs)} scheme parameter updates:")
            for d in diffs:
                logger.info(f"  [{d['scheme_id']}] {d['field']}: {d.get('old_value')} -> {d.get('new_value')}")
        else:
            logger.info("No numerical or managerial metric diffs detected. Advancing recency timestamps.")

        # 5. Semantic Chunking & Corpus compilation
        logger.info("Step 3/4: Generating semantic chunks with immutable context headers...")
        chunks = self.chunker.process_and_save_corpus(new_schemes)

        # 6. Optional ChromaDB vector index & BM25 index sync
        retrieval_sync_info: Dict[str, Any] = {}
        if sync_vector_index:
            try:
                from src.retrieval.bm25_indexer import BM25Indexer
                from src.retrieval.indexer import VectorIndexer
                logger.info("Step 4/4: Synchronizing corpus chunks into ChromaDB & BM25 indexes...")
                indexer = VectorIndexer(processed_dir=self.processed_dir)
                idx_summary = indexer.build_vector_index(force_reindex=False)

                bm25_idx = BM25Indexer(corpus_path=self.chunker.corpus_path, auto_load=False)
                bm25_summary = bm25_idx.build_index(force_rebuild=True)

                retrieval_sync_info = {
                    "vector_index_synced": True,
                    "vector_chunks_indexed": idx_summary["chunks_upserted"],
                    "total_collection_count": idx_summary["total_collection_count"],
                    "bm25_index_synced": True,
                    "bm25_chunks_indexed": bm25_summary["indexed_chunks"],
                }
            except Exception as e:
                logger.error(f"Failed to synchronize retrieval indexes: {e}")
                retrieval_sync_info = {
                    "retrieval_index_synced": False,
                    "retrieval_index_error": str(e),
                }

        elapsed = time.time() - start_time
        summary = {
            "status": "SUCCESS",
            "timestamp": now_str,
            "schemes_processed": len(new_schemes),
            "total_chunks_generated": len(chunks),
            "diffs_detected": len(diffs),
            "duration_seconds": round(elapsed, 2),
            "corpus_file": str(self.chunker.corpus_path),
            **retrieval_sync_info,
        }
        logger.info(f"=== Ingestion Pipeline Completed in {elapsed:.2f}s ===")
        logger.info(f"Summary: {json.dumps(summary, indent=2)}")
        return summary

    def start_scheduler_daemon(
        self,
        hour: int = SCHEDULER_HOUR,
        minute: int = SCHEDULER_MINUTE,
        timezone_name: str = SCHEDULER_TIMEZONE,
        blocking: bool = True,
    ):
        """Start recurring daily scheduler job at specified hour, minute, and timezone.
        
        Args:
            hour: Hour of day to trigger (default: SCHEDULER_HOUR = 10).
            minute: Minute of hour to trigger (default: SCHEDULER_MINUTE = 0).
            timezone_name: Timezone name (default: SCHEDULER_TIMEZONE = 'Asia/Kolkata').
            blocking: If True, blocks the process; if False, runs as background thread.
        """
        scheduler = BlockingScheduler() if blocking else BackgroundScheduler()
        trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone_name)

        scheduler.add_job(
            func=self.run_ingestion_pipeline,
            trigger=trigger,
            id="daily_mutual_fund_ingestion",
            name="Daily Groww Mutual Fund Data Refresh",
            replace_existing=True,
            kwargs={"force_refresh": True},
        )

        next_fire = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        logger.info(
            f"Scheduled daily mutual fund ingestion job at {hour:02d}:{minute:02d} ({timezone_name}). "
            f"Next run: {next_fire}"
        )
        if blocking:
            try:
                scheduler.start()
            except (KeyboardInterrupt, SystemExit):
                logger.info("Ingestion scheduler stopped by user.")
        else:
            scheduler.start()
            return scheduler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mutual Fund Data Ingestion Scheduler")
    parser.add_argument("--run-now", action="store_true", help="Execute immediate ingestion cycle")
    parser.add_argument("--force", action="store_true", help="Force live web scraping bypassing cache")
    parser.add_argument("--schedule", action="store_true", help="Start persistent daily scheduler")
    parser.add_argument("--hour", type=int, default=SCHEDULER_HOUR, help=f"Hour for daily schedule (0-23, default: {SCHEDULER_HOUR})")
    parser.add_argument("--minute", type=int, default=SCHEDULER_MINUTE, help=f"Minute for daily schedule (0-59, default: {SCHEDULER_MINUTE})")
    parser.add_argument("--timezone", type=str, default=SCHEDULER_TIMEZONE, help=f"Timezone for daily schedule (default: {SCHEDULER_TIMEZONE})")
    parser.add_argument("--skip-vector-sync", action="store_true", help="Skip synchronizing vector index")

    args = parser.parse_args()
    scheduler = IngestionScheduler()

    if args.run_now or not args.schedule:
        scheduler.run_ingestion_pipeline(
            force_refresh=args.force,
            sync_vector_index=not args.skip_vector_sync,
        )

    if args.schedule:
        scheduler.start_scheduler_daemon(
            hour=args.hour,
            minute=args.minute,
            timezone_name=args.timezone,
            blocking=True,
        )
