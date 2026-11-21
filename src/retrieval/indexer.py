"""Corpus vector indexing pipeline for mutual fund chunks into ChromaDB."""

import argparse
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union

from src.config import DATA_PROCESSED_DIR
from src.retrieval.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class VectorIndexer:
    """Orchestrates loading chunks from corpus.jsonl and indexing into ChromaDB."""

    def __init__(
        self,
        vector_store: Optional[ChromaVectorStore] = None,
        processed_dir: Optional[Union[str, Path]] = None,
    ):
        """Initialize the VectorIndexer.
        
        Args:
            vector_store: Instance of ChromaVectorStore or None to instantiate default.
            processed_dir: Directory containing processed corpus files.
        """
        self.processed_dir = Path(processed_dir or DATA_PROCESSED_DIR)
        self.vector_store = vector_store or ChromaVectorStore()

    def load_corpus(self, corpus_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
        """Load semantic chunks from corpus.jsonl or fallback to corpus.json.
        
        Args:
            corpus_path: Explicit path to corpus file, or None for default detection.
            
        Returns:
            List of chunk dictionaries.
        """
        if corpus_path:
            target_path = Path(corpus_path)
            if not target_path.exists():
                raise FileNotFoundError(f"Specified corpus file does not exist: {target_path}")
        else:
            jsonl_path = self.processed_dir / "corpus.jsonl"
            json_path = self.processed_dir / "corpus.json"
            if jsonl_path.exists():
                target_path = jsonl_path
            elif json_path.exists():
                target_path = json_path
            else:
                raise FileNotFoundError(
                    f"No corpus file found at '{jsonl_path}' or '{json_path}'. "
                    "Run Phase 1 ingestion first."
                )

        logger.info(f"Loading mutual fund corpus from '{target_path}'...")
        chunks: List[Dict[str, Any]] = []

        if target_path.suffix == ".jsonl":
            with open(target_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line_clean = line.strip()
                    if line_clean:
                        try:
                            chunks.append(json.loads(line_clean))
                        except json.JSONDecodeError as e:
                            logger.warning(f"Skipping malformed JSON line {line_num}: {e}")
        else:
            with open(target_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                if isinstance(raw_data, list):
                    chunks = raw_data
                elif isinstance(raw_data, dict) and "chunks" in raw_data:
                    chunks = raw_data["chunks"]

        logger.info(f"Loaded {len(chunks)} chunks from '{target_path}'.")
        return chunks

    def build_vector_index(
        self,
        force_reindex: bool = False,
        corpus_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Index all mutual fund corpus chunks into ChromaDB.
        
        Args:
            force_reindex: If True, resets existing collection before upserting.
            corpus_path: Optional explicit corpus file path.
            
        Returns:
            Execution summary dictionary with stats.
        """
        start_time = time.time()
        logger.info(f"=== Starting Vector Index Build (force_reindex={force_reindex}) ===")

        if force_reindex:
            self.vector_store.reset_collection()

        chunks = self.load_corpus(corpus_path=corpus_path)
        if not chunks:
            raise ValueError("Corpus is empty. No chunks to index.")

        upserted_count = self.vector_store.upsert_chunks(chunks)
        stats = self.vector_store.get_collection_stats()
        elapsed = time.time() - start_time

        summary = {
            "status": "SUCCESS",
            "chunks_upserted": upserted_count,
            "total_collection_count": stats["total_documents"],
            "vector_dimension": stats["vector_dimension"],
            "embedding_model": stats["embedding_model"],
            "scheme_distribution": stats["scheme_distribution"],
            "duration_seconds": round(elapsed, 2),
        }

        logger.info(f"=== Vector Index Build Completed in {elapsed:.2f}s ===")
        logger.info(f"Summary: {json.dumps(summary, indent=2)}")
        return summary


def main():
    """CLI driver for Vector Index management."""
    parser = argparse.ArgumentParser(description="Build and manage ChromaDB vector index for Mutual Fund RAG.")
    parser.add_argument("--build", action="store_true", help="Build or update vector index from corpus.jsonl.")
    parser.add_argument("--reindex", action="store_true", help="Reset collection and perform fresh re-indexing.")
    parser.add_argument("--stats", action="store_true", help="Print vector collection statistics.")
    parser.add_argument("--search", type=str, default=None, help="Run a test similarity search with query.")
    parser.add_argument("--k", type=int, default=3, help="Number of results for test search (default: 3).")
    parser.add_argument("--filter-scheme", type=str, default=None, help="Filter search to scheme_id.")

    args = parser.parse_args()
    indexer = VectorIndexer()

    if args.reindex:
        indexer.build_vector_index(force_reindex=True)
    elif args.build:
        indexer.build_vector_index(force_reindex=False)
    elif args.stats:
        stats = indexer.vector_store.get_collection_stats()
        print(json.dumps(stats, indent=2))
    elif args.search:
        filter_dict = {"scheme_id": args.filter_scheme} if args.filter_scheme else None
        results = indexer.vector_store.similarity_search(query=args.search, k=args.k, filter_dict=filter_dict)
        print(f"\n--- Top {len(results)} Search Results for: '{args.search}' ---")
        for i, hit in enumerate(results, 1):
            print(f"\nRank {i} [Score: {hit['score']:.4f} | Dist: {hit['distance']:.4f}]")
            print(f"Chunk ID: {hit['chunk_id']}")
            print(f"Scheme: {hit['metadata'].get('scheme_name')}")
            print(f"Section: {hit['metadata'].get('section')}")
            print(f"Text Snippet:\n{hit['text'][:200]}...")
    else:
        # Default action: display stats or run build if empty
        current_count = indexer.vector_store.count()
        if current_count == 0:
            print("ChromaDB collection is empty. Building index from corpus...")
            indexer.build_vector_index(force_reindex=False)
        else:
            stats = indexer.vector_store.get_collection_stats()
            print(f"Vector collection is active with {stats['total_documents']} documents.")
            print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
