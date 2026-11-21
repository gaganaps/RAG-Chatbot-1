"""Finance-aware lexical search indexer using Rank-BM25 with on-disk caching."""

import argparse
import json
import logging
from pathlib import Path
import pickle
import re
import time
from typing import Any, Dict, List, Optional, Set, Union

from rank_bm25 import BM25Okapi

from src.config import DATA_PROCESSED_DIR

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Conversational & English functional stopwords (domain-safe: preserves financial terms and query qualifiers)
FINANCE_STOPWORDS: Set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "of", "for", "to", "from",
    "by", "with", "about", "as", "into", "like", "through", "after", "over", "between", "out",
    "against", "during", "without", "before", "under", "around", "among", "what", "which", "who",
    "whom", "this", "that", "these", "those", "am", "been", "being", "have", "has", "had", "do",
    "does", "did", "but", "if", "or", "because", "until", "while", "how", "any", "can", "could",
    "should", "would", "tell", "me", "give", "please", "my", "your", "their", "its", "there",
}


def tokenize_finance(text: str, remove_stopwords: bool = True) -> List[str]:
    """Tokenize mutual fund text with financial symbol and acronym preservation.
    
    Preserves and expands:
      - Currency symbols & amounts: ₹100 -> ['₹100', '100'], ₹500 -> ['₹500', '500']
      - Percentages & rates: 0.74% -> ['0.74%', '0.74'], 1% -> ['1%', '1']
      - Acronyms: TER, SIP, FoF, AUM, NAV, TRI, ELSS, AMC, BAF
      - Hyphenated identifiers: flexi-cap, large-and-mid-cap, direct-growth
      - Proper names & general terms: Dhruv, Muchhal, Amit, Ganatra, expense, exit, load
    """
    if not text:
        return []

    # Clean punctuation except hyphen, percent, dot in decimals, and rupee symbol
    raw_tokens = re.findall(r"[A-Za-z0-9_.\-%₹]+", text)
    tokens: List[str] = []

    for tok in raw_tokens:
        tok_clean = tok.strip(".,;:!?()[]{}'\"")
        if not tok_clean:
            continue
        tok_lower = tok_clean.lower()
        if remove_stopwords and tok_lower in FINANCE_STOPWORDS:
            continue

        # Currency expansion: e.g. ₹100 -> '₹100' and '100'
        if tok_lower.startswith("₹") and len(tok_lower) > 1:
            tokens.append(tok_lower)
            num_part = tok_lower[1:]
            if num_part:
                tokens.append(num_part)
            continue

        # Percentage expansion: e.g. 0.74% -> '0.74%' and '0.74'
        if tok_lower.endswith("%") and len(tok_lower) > 1:
            tokens.append(tok_lower)
            num_part = tok_lower[:-1]
            if num_part:
                tokens.append(num_part)
            continue

        # Retain tokens with length > 1 or currency/digit
        if len(tok_lower) > 1 or tok_lower.isdigit() or tok_lower == "₹":
            tokens.append(tok_lower)

    return tokens


class BM25Indexer:
    """Manages Rank-BM25 inverted index for mutual fund knowledge corpus."""

    def __init__(
        self,
        corpus_path: Optional[Union[str, Path]] = None,
        index_cache_path: Optional[Union[str, Path]] = None,
        auto_load: bool = True,
    ):
        """Initialize the BM25 indexer.
        
        Args:
            corpus_path: Explicit path to corpus.jsonl / corpus.json.
            index_cache_path: Explicit path to cached serialized index.
            auto_load: If True, attempts loading cached index or builds fresh.
        """
        self.corpus_path = Path(corpus_path or (DATA_PROCESSED_DIR / "corpus.jsonl"))
        self.index_cache_path = Path(index_cache_path or (DATA_PROCESSED_DIR / "bm25_index.pkl"))
        self.chunks: List[Dict[str, Any]] = []
        self.bm25: Optional[BM25Okapi] = None
        self.tokenized_corpus: List[List[str]] = []

        if auto_load:
            self.load_or_build_index()

    def _load_corpus(self) -> List[Dict[str, Any]]:
        """Load chunks from corpus.jsonl or fallback to corpus.json."""
        target = self.corpus_path
        if not target.exists():
            json_alt = target.parent / "corpus.json"
            if json_alt.exists():
                target = json_alt
            else:
                raise FileNotFoundError(f"Corpus file not found at '{target}' or '{json_alt}'.")

        logger.info(f"Loading corpus from '{target}' for BM25 indexing...")
        chunks: List[Dict[str, Any]] = []
        if target.suffix == ".jsonl":
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line_clean = line.strip()
                    if line_clean:
                        chunks.append(json.loads(line_clean))
        else:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
                chunks = data if isinstance(data, list) else data.get("chunks", [])

        logger.info(f"Loaded {len(chunks)} chunks for BM25 indexer.")
        return chunks

    def build_index(self, force_rebuild: bool = False) -> Dict[str, Any]:
        """Build fresh BM25Okapi inverted index from corpus and persist to disk.
        
        Args:
            force_rebuild: If True, rebuilds even if cache exists.
            
        Returns:
            Build summary statistics.
        """
        start_time = time.time()
        logger.info("=== Starting BM25 Inverted Index Construction ===")

        self.chunks = self._load_corpus()
        if not self.chunks:
            raise ValueError("Cannot build BM25 index from empty corpus.")

        logger.info("Tokenizing corpus chunks with finance-aware tokenizer...")
        self.tokenized_corpus = [tokenize_finance(c["text"]) for c in self.chunks]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

        self.save_index()
        elapsed = time.time() - start_time

        summary = {
            "status": "SUCCESS",
            "indexed_chunks": len(self.chunks),
            "total_tokens": sum(len(toks) for toks in self.tokenized_corpus),
            "cache_path": str(self.index_cache_path),
            "duration_seconds": round(elapsed, 4),
        }
        logger.info(f"=== BM25 Index Construction Completed in {elapsed:.4f}s ===")
        logger.info(f"Summary: {json.dumps(summary, indent=2)}")
        return summary

    def save_index(self) -> None:
        """Serialize BM25 index, chunks, and tokenized representation to disk."""
        if not self.bm25 or not self.chunks:
            raise ValueError("No BM25 index to save. Build index first.")

        self.index_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chunks": self.chunks,
            "tokenized_corpus": self.tokenized_corpus,
            "corpus_mtime": self.corpus_path.stat().st_mtime if self.corpus_path.exists() else 0,
            "bm25": self.bm25,
        }
        with open(self.index_cache_path, "wb") as f:
            pickle.dump(payload, f)
        logger.info(f"Saved persistent BM25 index to '{self.index_cache_path}'.")

    def load_or_build_index(self) -> None:
        """Load index from pickle cache if valid, otherwise build fresh."""
        if self.index_cache_path.exists():
            try:
                with open(self.index_cache_path, "rb") as f:
                    payload = pickle.load(f)

                # Validate cache freshness against corpus mtime
                corpus_mtime = self.corpus_path.stat().st_mtime if self.corpus_path.exists() else 0
                if payload.get("corpus_mtime", 0) >= corpus_mtime and payload.get("bm25") is not None:
                    self.chunks = payload["chunks"]
                    self.tokenized_corpus = payload["tokenized_corpus"]
                    self.bm25 = payload["bm25"]
                    logger.info(
                        f"Loaded persistent BM25 index from cache '{self.index_cache_path}' "
                        f"({len(self.chunks)} chunks)."
                    )
                    return
                else:
                    logger.info("Corpus updated since last BM25 index cache. Rebuilding...")
            except Exception as e:
                logger.warning(f"Failed to load cached BM25 index: {e}. Rebuilding...")

        self.build_index(force_rebuild=True)

    def search(
        self,
        query: str,
        k: int = 20,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform sparse lexical search across indexed corpus.
        
        Args:
            query: User search query string.
            k: Maximum candidates to return.
            filter_dict: Optional metadata filter dict (e.g. {"scheme_id": "hdfc-flexi-cap"}).
            
        Returns:
            List of matching chunk dictionaries with 'score' and 'rank'.
        """
        if not self.bm25 or not self.chunks:
            self.load_or_build_index()

        q_tokens = tokenize_finance(query)
        if not q_tokens:
            return []

        scores = self.bm25.get_scores(q_tokens)
        scored_pairs = list(zip(self.chunks, scores))

        # Filter if filter_dict provided
        if filter_dict:
            filtered_pairs = []
            for chunk, score in scored_pairs:
                match = True
                for fk, fv in filter_dict.items():
                    if chunk.get(fk) != fv:
                        match = False
                        break
                if match:
                    filtered_pairs.append((chunk, score))
            scored_pairs = filtered_pairs

        # Sort descending by BM25 score
        sorted_pairs = sorted(scored_pairs, key=lambda x: x[1], reverse=True)

        results: List[Dict[str, Any]] = []
        for rank, (chunk, score) in enumerate(sorted_pairs[:k], start=1):
            if score <= 0.0 and len(results) > 0:
                # Discard zero-score documents if at least one match found
                break

            results.append({
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "metadata": {
                    "scheme_id": chunk.get("scheme_id"),
                    "scheme_name": chunk.get("scheme_name"),
                    "amc": chunk.get("amc"),
                    "category": chunk.get("category"),
                    "section": chunk.get("section"),
                    "source_url": chunk.get("source_url"),
                    "last_scraped_date": chunk.get("last_scraped_date"),
                    "token_count": chunk.get("token_count"),
                },
                "score": round(float(score), 4),
                "rank": rank,
            })

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics on indexed corpus."""
        return {
            "indexed_chunks": len(self.chunks),
            "cache_path": str(self.index_cache_path),
            "corpus_path": str(self.corpus_path),
            "total_tokens": sum(len(toks) for toks in self.tokenized_corpus) if self.tokenized_corpus else 0,
        }


def main():
    """CLI driver for BM25 indexer."""
    parser = argparse.ArgumentParser(description="Build and search BM25 lexical index.")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild BM25 index from corpus.jsonl")
    parser.add_argument("--search", type=str, default=None, help="Query string to search")
    parser.add_argument("--k", type=int, default=5, help="Number of results to return (default: 5)")
    parser.add_argument("--filter-scheme", type=str, default=None, help="Optional scheme_id filter")
    parser.add_argument("--stats", action="store_true", help="Display index stats")

    args = parser.parse_args()
    indexer = BM25Indexer(auto_load=not args.rebuild)

    if args.rebuild:
        indexer.build_index(force_rebuild=True)
    elif args.stats:
        print(json.dumps(indexer.get_stats(), indent=2))
    elif args.search:
        filter_dict = {"scheme_id": args.filter_scheme} if args.filter_scheme else None
        results = indexer.search(query=args.search, k=args.k, filter_dict=filter_dict)
        print(f"\n--- Top {len(results)} BM25 Results for: '{args.search}' ---")
        for hit in results:
            print(f"\nRank {hit['rank']} [BM25 Score: {hit['score']:.4f}]")
            print(f"Chunk ID: {hit['chunk_id']}")
            print(f"Scheme: {hit['metadata'].get('scheme_name')}")
            print(f"Section: {hit['metadata'].get('section')}")
            print(f"Text Snippet:\n{hit['text'][:180]}...")
    else:
        print(json.dumps(indexer.get_stats(), indent=2))


if __name__ == "__main__":
    main()
