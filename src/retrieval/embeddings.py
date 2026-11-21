"""Lightweight, open-source embedding engine using FastEmbed (ONNX) with SentenceTransformers fallback."""

import logging
import os
from typing import List, Optional

from src.config import EMBEDDING_MODEL_NAME

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class EmbeddingEngine:
    """Wrapper around FastEmbed (ONNX) and SentenceTransformers for local vector embedding."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        device: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = device or "cpu"
        self._use_fastembed = False
        self._dimension = 384

        # Primary: FastEmbed (pure ONNX - uses <50MB RAM, zero PyTorch/CUDA bloat)
        try:
            from fastembed import TextEmbedding
            logger.info(f"Loading lightweight ONNX embedding model '{self.model_name}' via FastEmbed...")
            self.model = TextEmbedding(model_name=self.model_name)
            self._use_fastembed = True
            logger.info("FastEmbed ONNX engine loaded successfully. Memory footprint: ~45 MB.")
        except Exception as e:
            logger.info(f"FastEmbed not available ({e}), falling back to SentenceTransformers...")
            import torch
            from sentence_transformers import SentenceTransformer
            if self.device == "cpu":
                torch.set_num_threads(1)
            torch.set_grad_enabled(False)
            self.model = SentenceTransformer(self.model_name, device=self.device)
            self.model.eval()
            self._dimension = self.model.get_sentence_embedding_dimension()
            logger.info(f"SentenceTransformers loaded. Vector dimension: {self._dimension}")

    @property
    def dimension(self) -> int:
        """The dimensionality of the output embedding vectors."""
        return self._dimension

    def embed_query(self, query: str) -> List[float]:
        """Generate normalized dense vector for a user search query.
        
        Args:
            query: User search query string.
            
        Returns:
            List of floats representing the L2-normalized vector.
        """
        cleaned_query = query.strip()
        if self._use_fastembed:
            vectors = list(self.model.embed([cleaned_query]))
            return vectors[0].tolist()
        else:
            import torch
            with torch.no_grad():
                embedding = self.model.encode(
                    cleaned_query,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
            return embedding.tolist()

    def embed_documents(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generate normalized dense vectors for a batch of documents.
        
        Args:
            texts: List of document strings.
            batch_size: Batch size for encoding.
            
        Returns:
            List of vector embeddings as float lists.
        """
        if not texts:
            return []

        cleaned_texts = [t.strip() for t in texts]
        if self._use_fastembed:
            vectors = list(self.model.embed(cleaned_texts, batch_size=batch_size))
            return [v.tolist() for v in vectors]
        else:
            import torch
            with torch.no_grad():
                embeddings = self.model.encode(
                    cleaned_texts,
                    batch_size=batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=len(texts) > 20,
                    convert_to_numpy=True,
                )
            return embeddings.tolist()


_GLOBAL_EMBEDDING_ENGINE: Optional[EmbeddingEngine] = None


def get_embedding_engine(model_name: str = EMBEDDING_MODEL_NAME) -> EmbeddingEngine:
    """Retrieve singleton instance of EmbeddingEngine to prevent redundant model loads."""
    global _GLOBAL_EMBEDDING_ENGINE
    if _GLOBAL_EMBEDDING_ENGINE is None or _GLOBAL_EMBEDDING_ENGINE.model_name != model_name:
        _GLOBAL_EMBEDDING_ENGINE = EmbeddingEngine(model_name=model_name)
    return _GLOBAL_EMBEDDING_ENGINE


if __name__ == "__main__":
    engine = get_embedding_engine()
    sample_text = "What is the exit load for HDFC Balanced Advantage Fund?"
    vec = engine.embed_query(sample_text)
    print(f"Model: {engine.model_name}")
    print(f"Device: {engine.device}")
    print(f"Vector Dimension: {len(vec)}")
    print(f"Sample values: {vec[:5]}")
