"""
RecruitScreen v1.0 — Per-Candidate FAISS Resume Index
───────────────────────────────────────────────────────
Builds a small FAISS vector index over chunked resume text.
Used by EvidenceRetrievalAgent to find passages relevant to a skill claim.

Usage:
    idx = ResumeIndex("john_doe_id")
    idx.build(resume_text)
    results = idx.search("REST API development", top_k=3)
    # returns [{"chunk": str, "score": float, "chunk_id": int}, ...]
"""

import numpy as np
from .embedder import get_embedder


class ResumeIndex:
    """
    FAISS-backed index of chunked resume text for one candidate.
    Falls back to BM25-style numpy dot product if faiss-cpu is not installed.
    """

    def __init__(self, candidate_id: str, chunk_size: int = 200, overlap: int = 50):
        self.candidate_id = candidate_id
        self.chunk_size   = chunk_size
        self.overlap      = overlap
        self._chunks:     list[str]       = []
        self._embeddings: np.ndarray | None = None
        self._index       = None          # faiss.IndexFlatIP or None
        self._built       = False

    # ── Build ─────────────────────────────────────────────────────────

    def build(self, resume_text: str) -> int:
        """
        Chunk the resume and build an embedding index.

        Returns:
            Number of chunks indexed.
        """
        self._chunks = self._chunk_text(resume_text)
        if not self._chunks:
            return 0

        embedder          = get_embedder()
        self._embeddings  = embedder.embed_batch(self._chunks)

        # Try to build FAISS index
        try:
            import faiss
            dim         = self._embeddings.shape[1]
            index       = faiss.IndexFlatIP(dim)   # Inner product = cosine (normalized)
            index.add(self._embeddings.astype("float32"))
            self._index = index
            print(f"[ResumeIndex] FAISS index built: {len(self._chunks)} chunks "
                  f"for candidate {self.candidate_id}")
        except ImportError:
            # Fallback: pure numpy dot-product search
            self._index = None
            print(f"[ResumeIndex] faiss not available, using numpy fallback. "
                  f"Install with: pip install faiss-cpu")

        self._built = True
        return len(self._chunks)

    # ── Search ────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Find the most relevant resume chunks for a query.

        Returns:
            list of {chunk_id, chunk, score} sorted desc by score
        """
        if not self._built or not self._chunks:
            return []

        embedder  = get_embedder()
        q_emb     = embedder.embed(query).astype("float32")

        if self._index is not None:
            # FAISS path
            k            = min(top_k, len(self._chunks))
            scores, idxs = self._index.search(q_emb.reshape(1, -1), k)
            results = [
                {
                    "chunk_id": int(idxs[0][i]),
                    "chunk":    self._chunks[int(idxs[0][i])],
                    "score":    float(scores[0][i]),
                }
                for i in range(k)
                if idxs[0][i] >= 0
            ]
        else:
            # Numpy fallback
            sims      = (self._embeddings @ q_emb).flatten()
            top_idxs  = np.argsort(sims)[::-1][:top_k]
            results = [
                {
                    "chunk_id": int(i),
                    "chunk":    self._chunks[i],
                    "score":    float(sims[i]),
                }
                for i in top_idxs
            ]

        # Filter very low scores (irrelevant chunks)
        results = [r for r in results if r["score"] > 0.15]
        return results

    # ── Helpers ───────────────────────────────────────────────────────

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into overlapping word-based chunks.
        200 words per chunk, 50-word overlap.
        """
        words  = text.split()
        chunks = []
        step   = self.chunk_size - self.overlap

        for i in range(0, max(len(words) - self.overlap, 1), step):
            chunk = " ".join(words[i : i + self.chunk_size])
            if chunk.strip():
                chunks.append(chunk.strip())

        # Always include at least one chunk even for very short resumes
        if not chunks and words:
            chunks.append(" ".join(words))

        return chunks

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def is_built(self) -> bool:
        return self._built
