"""Hybrid retrieval engine combining Dense Vector Search (ChromaDB) and Sparse BM25 with RRF."""

import argparse
from dataclasses import asdict, dataclass
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import ACTIVE_SCHEMES, SIMILARITY_CONFIDENCE_THRESHOLD
from src.retrieval.bm25_indexer import BM25Indexer
from src.retrieval.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@dataclass
class RetrievalResult:
    """Standardized retrieval output unit containing text, scheme metadata, and provenance scores."""
    chunk_id: str
    scheme_id: str
    scheme_name: str
    section: str
    source_url: str
    last_scraped_date: str
    text: str
    rrf_score: float
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result object to dictionary."""
        return asdict(self)


class SchemeEntityResolver:
    """Heuristic resolver to detect mutual fund scheme mentions in queries."""

    # Curated keyword aliases mapped to canonical scheme_id
    SCHEME_ALIASES: Dict[str, List[str]] = {
        "hdfc-flexi-cap": [
            "flexi cap",
            "flexicap",
            "flexi-cap",
            "hdfc flexi",
            "hdfc equity fund",
            "hdfc equity",
            "hdfc-equity-fund",
            "hdfc-flexi-cap",
        ],
        "hdfc-silver-etf-fof": [
            "silver",
            "silver etf",
            "silver fof",
            "silver-etf",
            "hdfc silver",
            "hdfc-silver-etf",
        ],
        "hdfc-balanced-advantage": [
            "balanced advantage",
            "balanced-advantage",
            "baf",
            "dynamic asset allocation",
            "dynamic asset",
            "hdfc balanced",
            "hdfc-balanced-advantage",
        ],
        "hdfc-large-and-mid-cap": [
            "large and mid cap",
            "large and mid",
            "large & mid",
            "large mid cap",
            "large mid",
            "large cap",
            "large-cap",
            "hdfc large",
            "hdfc-large-mid-cap",
            "hdfc-large-cap",
        ],
        "hdfc-manufacturing": [
            "manufacturing fund",
            "manufacturing",
            "thematic fund",
            "thematic",
            "hdfc manufacturing",
            "hdfc-manufacturing",
        ],
    }

    def resolve_scheme(self, query: str) -> Optional[str]:
        """Detect if user query unambiguously references an active scheme.
        
        Args:
            query: Normalized user query string.
            
        Returns:
            Matched canonical scheme_id, or None if ambiguous/unmentioned.
        """
        q_lower = query.lower()
        matched_schemes: Set[str] = set()

        for scheme_id, aliases in self.SCHEME_ALIASES.items():
            for alias in aliases:
                # Word boundary check for short terms like 'baf' or 'silver'
                pattern = r"\b" + re.escape(alias) + r"\b"
                if re.search(pattern, q_lower):
                    matched_schemes.add(scheme_id)
                    break

        # If exactly one scheme matches unambiguously, return it
        if len(matched_schemes) == 1:
            return next(iter(matched_schemes))

        # If multiple or zero schemes match, return None to trigger global search or ambiguity handling
        return None

    resolve = resolve_scheme


class HybridRetriever:
    """Unifies dense vector retrieval (ChromaDB) and lexical search (BM25) via RRF."""

    def __init__(
        self,
        vector_store: Optional[ChromaVectorStore] = None,
        bm25_indexer: Optional[BM25Indexer] = None,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ):
        """Initialize the hybrid retriever.
        
        Args:
            vector_store: Persistent ChromaVectorStore instance.
            bm25_indexer: Persistent BM25Indexer instance.
            rrf_k: Constant denominator shift for Reciprocal Rank Fusion (standard: 60).
            dense_weight: Relative weighting for dense vector rank component.
            sparse_weight: Relative weighting for BM25 lexical rank component.
        """
        self.vector_store = vector_store or ChromaVectorStore()
        self.bm25_indexer = bm25_indexer or BM25Indexer()
        self.scheme_resolver = SchemeEntityResolver()
        self.entity_resolver = self.scheme_resolver
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight

    def retrieve(
        self,
        query: str,
        k: int = 3,
        scheme_id: Optional[str] = None,
        candidate_pool_k: int = 20,
        auto_resolve_scheme: bool = True,
        top_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """Perform hybrid retrieval using Dense + BM25 + Reciprocal Rank Fusion.
        
        Args:
            query: User search query.
            k: Number of final fused results to return (default: 3).
            scheme_id: Optional explicit scheme filter.
            candidate_pool_k: Number of candidate chunks to fetch from each retriever.
            auto_resolve_scheme: If True and scheme_id is None, infers scheme from query.
            top_k: Optional alias for k.
            
        Returns:
            Top-k RetrievalResult objects ordered descending by RRF score.
        """
        if top_k is not None:
            k = top_k
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        # 1. Resolve scheme filter if applicable
        target_scheme = scheme_id
        if not target_scheme and auto_resolve_scheme:
            target_scheme = self.scheme_resolver.resolve_scheme(cleaned_query)
            if target_scheme:
                logger.info(f"Auto-resolved scheme from query: '{target_scheme}'")

        filter_dict = {"scheme_id": target_scheme} if target_scheme else None

        # 2. Dense Vector Retrieval (ChromaDB)
        dense_hits = self.vector_store.similarity_search(
            query=cleaned_query,
            k=candidate_pool_k,
            filter_dict=filter_dict,
        )

        # 3. Sparse Lexical Retrieval (BM25)
        # When filtered to a scheme, extract the core question terms to prevent
        # the scheme name itself (present in every chunk) from dominating lexical ranks
        sparse_query = cleaned_query
        if target_scheme:
            for alias in self.scheme_resolver.SCHEME_ALIASES.get(target_scheme, []):
                sparse_query = re.sub(r"\b" + re.escape(alias) + r"\b", "", sparse_query, flags=re.IGNORECASE)
            sparse_query_cleaned = re.sub(r"\b(hdfc|fund|mutual)\b", "", sparse_query, flags=re.IGNORECASE).strip()
            if sparse_query_cleaned:
                sparse_query = sparse_query_cleaned

        sparse_hits = self.bm25_indexer.search(
            query=sparse_query,
            k=candidate_pool_k,
            filter_dict=filter_dict,
        )

        # 4. Reciprocal Rank Fusion (RRF)
        fused_results = self._fuse_rankings(
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            top_k=k,
        )

        return fused_results

    def _fuse_rankings(
        self,
        dense_hits: List[Dict[str, Any]],
        sparse_hits: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> List[RetrievalResult]:
        """Fuse dense and sparse candidate rankings via weighted Reciprocal Rank Fusion."""
        dense_map: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        for rank, hit in enumerate(dense_hits, start=1):
            dense_map[hit["chunk_id"]] = (rank, hit)

        sparse_map: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        for rank, hit in enumerate(sparse_hits, start=1):
            if hit.get("score", 0.0) > 0.0:
                sparse_map[hit["chunk_id"]] = (rank, hit)

        all_chunk_ids = set(dense_map.keys()) | set(sparse_map.keys())
        scored_candidates: List[Tuple[str, float, Optional[int], Optional[int], Optional[float], Optional[float], Dict[str, Any]]] = []

        for cid in all_chunk_ids:
            dense_rank, dense_hit = dense_map.get(cid, (None, None))
            sparse_rank, sparse_hit = sparse_map.get(cid, (None, None))

            # Retrieve chunk text and metadata from whichever hit is present
            ref_hit = dense_hit if dense_hit is not None else sparse_hit
            if not ref_hit:
                continue

            rrf_score = 0.0
            if dense_rank is not None:
                rrf_score += self.dense_weight / (self.rrf_k + dense_rank)
            if sparse_rank is not None:
                rrf_score += self.sparse_weight / (self.rrf_k + sparse_rank)

            dense_score = dense_hit["score"] if dense_hit else None
            sparse_score = sparse_hit["score"] if sparse_hit else None

            scored_candidates.append((
                cid,
                rrf_score,
                dense_rank,
                sparse_rank,
                dense_score,
                sparse_score,
                ref_hit,
            ))

        # Sort descending by RRF score; tie-break on dense score, then sparse score
        scored_candidates.sort(
            key=lambda x: (
                x[1],  # rrf_score
                x[4] if x[4] is not None else 0.0,  # dense_score
                x[5] if x[5] is not None else 0.0,  # sparse_score
            ),
            reverse=True,
        )

        results: List[RetrievalResult] = []
        for cid, rrf_score, d_rank, s_rank, d_score, s_score, ref_hit in scored_candidates[:top_k]:
            meta = ref_hit.get("metadata", {})
            results.append(RetrievalResult(
                chunk_id=cid,
                scheme_id=meta.get("scheme_id", "unknown"),
                scheme_name=meta.get("scheme_name", "Unknown Scheme"),
                section=meta.get("section", "unknown"),
                source_url=meta.get("source_url", ""),
                last_scraped_date=meta.get("last_scraped_date", ""),
                text=ref_hit.get("text", ""),
                rrf_score=round(rrf_score, 6),
                dense_rank=d_rank,
                sparse_rank=s_rank,
                dense_score=round(d_score, 4) if d_score is not None else None,
                sparse_score=round(s_score, 4) if s_score is not None else None,
            ))

        return results

    def check_confidence(
        self,
        results: List[RetrievalResult],
        min_dense_score: float = SIMILARITY_CONFIDENCE_THRESHOLD,
        min_bm25_score: float = 5.0,
    ) -> bool:
        """Validate if top retrieved chunk possesses sufficient factual relevance.
        
        Args:
            results: List of retrieved results.
            min_dense_score: Minimum dense cosine similarity threshold (default 0.65).
            min_bm25_score: Minimum standalone BM25 score threshold (default 5.0).
            
        Returns:
            True if confident, False if out-of-domain or low-confidence.
        """
        if not results:
            return False

        top = results[0]
        d_score = top.dense_score
        b_score = top.sparse_score

        # 1. Strong semantic match (dense >= min_dense_score, e.g. 0.65)
        if d_score is not None and d_score >= min_dense_score:
            return True
        # 2. Dominant exact keyword match (bm25 >= min_bm25_score, e.g. 5.0)
        if b_score is not None and b_score >= min_bm25_score:
            return True
        # 3. High consensus across modalities (dense >= 0.60 AND bm25 >= 3.0)
        if d_score is not None and d_score >= 0.60 and b_score is not None and b_score >= 3.0:
            return True

        return False


def main():
    """CLI driver for testing hybrid retrieval."""
    parser = argparse.ArgumentParser(description="Hybrid Retrieval (Dense + BM25 + RRF)")
    parser.add_argument("--query", type=str, required=True, help="Search query")
    parser.add_argument("--k", type=int, default=3, help="Top k results to return")
    parser.add_argument("--scheme", type=str, default=None, help="Explicit scheme_id filter")
    parser.add_argument("--no-auto-scheme", action="store_true", help="Disable auto-resolution of scheme")

    args = parser.parse_args()
    retriever = HybridRetriever()

    results = retriever.retrieve(
        query=args.query,
        k=args.k,
        scheme_id=args.scheme,
        auto_resolve_scheme=not args.no_auto_scheme,
    )
    is_confident = retriever.check_confidence(results)

    print(f"\n=== Hybrid Retrieval Results (k={args.k}) ===")
    print(f"Query: '{args.query}'")
    print(f"Confidence Passed: {is_confident}\n")

    for i, r in enumerate(results, start=1):
        print(f"Rank {i} [RRF Score: {r.rrf_score:.5f}]")
        print(f"  Chunk ID:     {r.chunk_id}")
        print(f"  Scheme:       {r.scheme_name} ({r.scheme_id})")
        print(f"  Section:      {r.section}")
        print(f"  Source URL:   {r.source_url}")
        print(f"  Last Scraped: {r.last_scraped_date}")
        print(f"  Dense:        Rank={r.dense_rank}, Score={r.dense_score}")
        print(f"  BM25:         Rank={r.sparse_rank}, Score={r.sparse_score}")
        print(f"  Text:\n{r.text[:220]}...\n")


if __name__ == "__main__":
    main()
