"""Persistent ChromaDB vector store wrapper for semantic chunk storage and retrieval."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import chromadb
from chromadb.api.models.Collection import Collection

from src.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR
from src.retrieval.embeddings import EmbeddingEngine, get_embedding_engine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ChromaVectorStore:
    """Manages persistent ChromaDB vector storage and semantic similarity search."""

    def __init__(
        self,
        persist_dir: Optional[Union[str, Path]] = None,
        collection_name: str = CHROMA_COLLECTION_NAME,
        embedding_engine: Optional[EmbeddingEngine] = None,
    ):
        """Initialize persistent ChromaDB client and target collection.
        
        Args:
            persist_dir: Local filesystem path where ChromaDB persists data.
            collection_name: Target collection identifier.
            embedding_engine: Custom EmbeddingEngine or None for global singleton.
        """
        self.persist_dir = Path(persist_dir or CHROMA_PERSIST_DIR)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_engine = embedding_engine or get_embedding_engine()

        logger.info(f"Connecting to persistent ChromaDB at '{self.persist_dir}'...")
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection: Collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"ChromaDB collection '{self.collection_name}' ready. "
            f"Current document count: {self.collection.count()}"
        )

    def count(self) -> int:
        """Return the number of vectors stored in the collection."""
        return self.collection.count()

    def reset_collection(self) -> None:
        """Purge and recreate the collection."""
        logger.warning(f"Resetting collection '{self.collection_name}' at '{self.persist_dir}'...")
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception as e:
            logger.info(f"Collection delete encountered non-fatal note: {e}")
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Collection '{self.collection_name}' successfully reset.")

    def _prepare_metadata(self, chunk: Dict[str, Any]) -> Dict[str, Union[str, int, float, bool]]:
        """Extract and sanitize chunk metadata into ChromaDB-compatible primitive types."""
        allowed_keys = [
            "scheme_id",
            "scheme_name",
            "amc",
            "category",
            "section",
            "source_url",
            "last_scraped_date",
            "token_count",
        ]
        meta: Dict[str, Union[str, int, float, bool]] = {}
        for key in allowed_keys:
            val = chunk.get(key)
            if val is not None:
                if isinstance(val, (str, int, float, bool)):
                    meta[key] = val
                else:
                    meta[key] = str(val)
        return meta

    def upsert_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None,
        batch_size: int = 50,
    ) -> int:
        """Upsert semantic chunks into ChromaDB with idempotency on chunk_id.
        
        Args:
            chunks: List of chunk dictionaries containing 'chunk_id', 'text', and metadata.
            embeddings: Optional precomputed embeddings. If None, computed on the fly.
            batch_size: Batch size for embedding and upsert operations.
            
        Returns:
            Count of upserted records.
        """
        if not chunks:
            logger.warning("No chunks provided to upsert.")
            return 0

        total_chunks = len(chunks)
        logger.info(f"Starting upsert of {total_chunks} chunks into '{self.collection_name}'...")

        # Compute embeddings if not provided
        if embeddings is None:
            texts = [c["text"] for c in chunks]
            logger.info(f"Encoding {len(texts)} document texts via {self.embedding_engine.model_name}...")
            embeddings = self.embedding_engine.embed_documents(texts, batch_size=batch_size)

        if len(embeddings) != total_chunks:
            raise ValueError(f"Embeddings count ({len(embeddings)}) != chunks count ({total_chunks})")

        # Process in batches
        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_embeddings = embeddings[i : i + batch_size]

            ids = [c["chunk_id"] for c in batch_chunks]
            documents = [c["text"] for c in batch_chunks]
            metadatas = [self._prepare_metadata(c) for c in batch_chunks]

            self.collection.upsert(
                ids=ids,
                embeddings=batch_embeddings,
                documents=documents,
                metadatas=metadatas,
            )

        logger.info(f"Successfully upserted {total_chunks} chunks. Collection count now: {self.count()}")
        return total_chunks

    def similarity_search(
        self,
        query: str,
        k: int = 3,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic similarity search using natural language query.
        
        Args:
            query: User search query.
            k: Top-k results to return.
            filter_dict: Optional metadata filter dict (e.g. {"scheme_id": "hdfc-flexi-cap"}).
            
        Returns:
            List of matching records sorted descending by similarity score.
        """
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        query_vec = self.embedding_engine.embed_query(cleaned_query)
        return self.similarity_search_by_vector(query_vec, k=k, filter_dict=filter_dict)

    def similarity_search_by_vector(
        self,
        query_vector: List[float],
        k: int = 3,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search collection by precomputed dense vector.
        
        Args:
            query_vector: L2-normalized float vector.
            k: Top-k results to return.
            filter_dict: Optional metadata filter dict.
            
        Returns:
            List of search hits with score, distance, chunk_id, text, and metadata.
        """
        # Ensure k does not exceed current collection size
        collection_size = self.count()
        if collection_size == 0:
            logger.warning("Search called on empty vector collection.")
            return []

        search_k = min(k, collection_size)
        query_args: Dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": search_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if filter_dict:
            query_args["where"] = filter_dict

        results = self.collection.query(**query_args)

        formatted_results: List[Dict[str, Any]] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists):
            # ChromaDB cosine distance = 1 - cosine_similarity
            cosine_similarity = max(0.0, min(1.0, 1.0 - float(dist)))
            formatted_results.append({
                "chunk_id": chunk_id,
                "text": doc,
                "metadata": meta,
                "score": round(cosine_similarity, 4),
                "distance": round(float(dist), 4),
            })

        return formatted_results

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific chunk document and metadata by chunk_id."""
        result = self.collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas", "embeddings"],
        )
        ids = result.get("ids", [])
        if not ids:
            return None

        return {
            "chunk_id": ids[0],
            "text": result["documents"][0] if result.get("documents") else "",
            "metadata": result["metadatas"][0] if result.get("metadatas") else {},
            "embedding": result["embeddings"][0] if result.get("embeddings") is not None else None,
        }

    def get_collection_stats(self) -> Dict[str, Any]:
        """Generate high-level health and distribution statistics for the collection."""
        total_count = self.count()
        scheme_distribution: Dict[str, int] = {}

        if total_count > 0:
            # Query all metadata without pulling embeddings to aggregate counts
            all_records = self.collection.get(include=["metadatas"])
            for meta in all_records.get("metadatas", []):
                sid = meta.get("scheme_id", "unknown")
                scheme_distribution[sid] = scheme_distribution.get(sid, 0) + 1

        return {
            "collection_name": self.collection_name,
            "persist_directory": str(self.persist_dir),
            "total_documents": total_count,
            "embedding_model": self.embedding_engine.model_name,
            "vector_dimension": self.embedding_engine.dimension,
            "scheme_distribution": scheme_distribution,
        }
