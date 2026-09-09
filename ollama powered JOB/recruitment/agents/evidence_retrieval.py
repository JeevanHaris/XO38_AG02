"""
RecruitScreen v1.0 — Evidence Retrieval Agent
───────────────────────────────────────────────
Uses Sentence Transformers + FAISS to find resume passages
that are semantically relevant to a skill claim.

This is the "find" step — the Verifier Agent then judges the found evidence.
"""

from ..models import Claim, Evidence, CandidateProfile
from ..semantic.resume_index import ResumeIndex
from ..semantic.embedder     import get_embedder


class EvidenceRetrievalAgent:
    """
    Retrieves the most semantically relevant resume passages for a skill claim.

    Pipeline:
      1. Build FAISS index of candidate resume (chunks of 200 words, 50 overlap)
      2. For each claim, embed the JD skill as query
      3. Find top-3 most similar resume chunks
      4. Return as Evidence objects for the Verifier to judge
    """

    TOP_K = 3   # max evidence passages per claim

    def __init__(self):
        self._indexes: dict[str, ResumeIndex] = {}  # candidate_id → ResumeIndex

    def build_index(self, profile: CandidateProfile) -> int:
        """
        Build (or rebuild) the FAISS index for a candidate's resume.

        Args:
            profile: CandidateProfile with raw_text

        Returns:
            Number of chunks indexed.
        """
        if not profile.raw_text:
            return 0

        index = ResumeIndex(profile.candidate_id)
        n     = index.build(profile.raw_text)
        self._indexes[profile.candidate_id] = index
        return n

    def retrieve(self, claim: Claim, profile: CandidateProfile) -> list[Evidence]:
        """
        Retrieve the most relevant resume passages for a single claim.

        Args:
            claim:   The claim to find evidence for (uses claim.jd_skill as query)
            profile: The candidate's profile

        Returns:
            list[Evidence] sorted by relevance score (desc)
        """
        # Ensure index exists
        if profile.candidate_id not in self._indexes:
            n = self.build_index(profile)
            if n == 0:
                return []

        index = self._indexes[profile.candidate_id]

        # Use the JD skill as the search query (semantic: what are we looking for?)
        query = claim.jd_skill or claim.skill

        # Enrich query with the claim statement if available
        if claim.statement:
            query = f"{query}: {claim.statement}"

        raw_results = index.search(query, top_k=self.TOP_K)

        evidence_list = []
        for r in raw_results:
            evidence_list.append(Evidence(
                chunk_text       = r["chunk"],
                similarity_score = r["score"],
                source_section   = self._infer_section(r["chunk"]),
            ))

        return evidence_list

    def retrieve_all(
        self,
        claims:  list[Claim],
        profile: CandidateProfile,
    ) -> dict[str, list[Evidence]]:
        """
        Retrieve evidence for all claims in one pass.

        Returns:
            dict mapping claim.jd_skill → list[Evidence]
        """
        # Ensure index is built once
        if profile.candidate_id not in self._indexes:
            self.build_index(profile)

        results = {}
        for claim in claims:
            key = claim.jd_skill or claim.skill
            evidence = self.retrieve(claim, profile)
            results[key] = evidence
            print(f"[EvidenceRetrieval] {profile.name} | '{key}': "
                  f"{len(evidence)} passages found "
                  f"(top score: {evidence[0].similarity_score:.3f if evidence else 0:.3f})")

        return results

    @staticmethod
    def _infer_section(chunk_text: str) -> str:
        """
        Heuristic: guess which resume section a chunk belongs to
        based on keywords at the start of the chunk.
        """
        text_lower = chunk_text.lower()[:100]
        section_keywords = {
            "Work Experience": ["experience", "worked", "employment", "position"],
            "Skills":          ["skills", "technologies", "proficient", "expertise"],
            "Projects":        ["project", "built", "developed", "created", "implemented"],
            "Education":       ["university", "college", "bachelor", "master", "degree", "b.tech", "m.tech"],
            "Certifications":  ["certified", "certification", "aws", "gcp", "azure certified"],
            "Summary":         ["summary", "objective", "profile", "about"],
        }
        for section, keywords in section_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return section
        return "Resume"
