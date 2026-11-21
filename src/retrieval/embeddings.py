"""Local, open-source embedding engine using sentence-transformers."""

import logging
import os
from typing import List, Optional

# Set HF_HUB_OFFLINE to 1 by default if offline / running locally without network
# to prevent sentence-transformers from hanging on huggingface.co connection retries
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_MODEL_NAME

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def detect_optimal_device() -> str:
    """Auto-detect the fastest available computation hardware."""
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        logger.info("Hardware acceleration: Apple Silicon (MPS) detected.")
        return "mps"
    if torch.cuda.is_available():
        logger.info(f"Hardware acceleration: NVIDIA CUDA detected ({torch.cuda.get_device_name(0)}).")
        return "cuda"
    logger.info("Hardware acceleration: CPU will be used.")
    return "cpu"


class EmbeddingEngine:
    """Wrapper around sentence-transformers models for local vector embedding."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        device: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = device or detect_optimal_device()

        # Cloud/Low-RAM optimization: Limit CPU threads & disable gradients to safely fit 512MB RAM
        if self.device == "cpu":
            torch.set_num_threads(1)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                pass
        torch.set_grad_enabled(False)

        logger.info(f"Loading local embedding model '{self.model_name}' on device '{self.device}'...")
        self.model = SentenceTransformer(self.model_name, device=self.device)
        self.model.eval()
        self._dimension = self.model.get_sentence_embedding_dimension()
        logger.info(f"Embedding model loaded successfully. Vector dimension: {self._dimension}")

        # Reclaim initialization memory buffers
        import gc
        gc.collect()

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
