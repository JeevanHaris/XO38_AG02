"""
RecruitScreen v1.0 — Semantic Embedder
────────────────────────────────────────
Singleton wrapper around SentenceTransformer for all embedding needs.

Model: all-MiniLM-L6-v2 (~80MB)
  - 384-dimensional vectors
  - Fast on CPU, good semantic quality
  - Perfect for skill similarity matching

Usage:
    embedder = get_embedder()
    vec = embedder.embed("Python FastAPI development")
    sim = embedder.cosine_similarity(vec1, vec2)
"""

import numpy as np

# Singleton instance — model loads once, reused everywhere
_embedder_instance = None


class RecruitmentEmbedder:
    """Lightweight SentenceTransformer wrapper for recruitment tasks."""

    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self):
        self._model = None
        self._model_loaded = False

    def _load(self):
        """Lazy-load the model on first use."""
        if self._model_loaded:
            return
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[Embedder] Loading {self.MODEL_NAME}...")
            self._model = SentenceTransformer(self.MODEL_NAME)
            self._model_loaded = True
            print(f"[Embedder] {self.MODEL_NAME} loaded.")
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text string → (384,) float32 array."""
        self._load()
        return self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Embed a list of strings → (N, 384) float32 array."""
        self._load()
        return self._model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        Cosine similarity between two normalized vectors.
        Since we normalize on encode, this is just dot product.
        """
        return float(np.dot(a, b))

    def similarity_matrix(
        self, texts_a: list[str], texts_b: list[str]
    ) -> np.ndarray:
        """
        Compute pairwise cosine similarities between two lists.
        Returns (len(texts_a), len(texts_b)) matrix.
        """
        emb_a = self.embed_batch(texts_a)
        emb_b = self.embed_batch(texts_b)
        return emb_a @ emb_b.T    # dot product = cosine sim (normalized vecs)

    def top_match(
        self,
        query: str,
        candidates: list[str],
        threshold: float = 0.35,
    ) -> tuple[int, float]:
        """
        Find the index and score of the best matching string in candidates.

        Returns:
            (best_index, best_score) — best_index is -1 if nothing meets threshold
        """
        if not candidates:
            return -1, 0.0

        q_emb = self.embed(query)
        c_emb = self.embed_batch(candidates)
        sims  = c_emb @ q_emb

        best_idx   = int(np.argmax(sims))
        best_score = float(sims[best_idx])

        if best_score < threshold:
            return -1, best_score
        return best_idx, best_score


def get_embedder() -> RecruitmentEmbedder:
    """Return the singleton embedder (load model on first call)."""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = RecruitmentEmbedder()
    return _embedder_instance
