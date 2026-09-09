"""
RecruitScreen v1.0 — Semantic Skill Matcher
─────────────────────────────────────────────
Uses Sentence Transformer embeddings to semantically match
JD skills with candidate skills — handles synonyms and paraphrases.

Examples:
  "PostgreSQL" ↔ "Postgres"            → semantic match
  "REST API development" ↔ "FastAPI"  → semantic match  
  "Kubernetes" ↔ "Java"               → no match

No LLM calls — purely embedding-based, deterministic and fast.
"""

from ..models import JDAnalysis, CandidateProfile, SkillMatch
from ..semantic.embedder import get_embedder


class SemanticSkillMatcher:
    """
    Matches JD required/preferred skills against candidate skills
    using cosine similarity on Sentence Transformer embeddings.
    """

    STRONG_MATCH_THRESHOLD  = 0.80   # Considered a clear match
    SEMANTIC_MATCH_THRESHOLD = 0.55   # Considered a semantic match
    EXACT_MATCH_BONUS        = 1.0    # Override: exact string match

    def __init__(self):
        self._embedder = None   # Lazy-loaded

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def match_required_skills(
        self,
        jd_analysis:  JDAnalysis,
        profile:      CandidateProfile,
    ) -> list[SkillMatch]:
        """
        Match all JD required skills against candidate's skill list.

        Returns:
            list[SkillMatch] — one per required JD skill
        """
        return self._match_skill_list(
            jd_skills       = jd_analysis.required_skills,
            candidate_skills = profile.skills,
        )

    def match_preferred_skills(
        self,
        jd_analysis:  JDAnalysis,
        profile:      CandidateProfile,
    ) -> list[SkillMatch]:
        """Match JD preferred skills against candidate's skill list."""
        return self._match_skill_list(
            jd_skills        = jd_analysis.preferred_skills,
            candidate_skills = profile.skills,
        )

    def _match_skill_list(
        self,
        jd_skills:        list[str],
        candidate_skills: list[str],
    ) -> list[SkillMatch]:
        """
        Core matching: for each JD skill, find best candidate skill match.
        """
        if not jd_skills:
            return []

        if not candidate_skills:
            return [
                SkillMatch(
                    jd_skill        = s,
                    candidate_skill = "",
                    similarity      = 0.0,
                    matched         = False,
                    match_type      = "none",
                )
                for s in jd_skills
            ]

        embedder = self._get_embedder()

        # First pass: exact / normalized exact matches (fast)
        results   = []
        remaining = []    # JD skills that need embedding search

        candidate_lower = {s.lower().strip(): s for s in candidate_skills}

        for jd_skill in jd_skills:
            jd_lower = jd_skill.lower().strip()

            # Exact match
            if jd_lower in candidate_lower:
                results.append(SkillMatch(
                    jd_skill        = jd_skill,
                    candidate_skill = candidate_lower[jd_lower],
                    similarity      = 1.0,
                    matched         = True,
                    match_type      = "exact",
                ))
                continue

            # Substring match (e.g. "PostgreSQL" ↔ "Postgres")
            substring_match = None
            for c_lower, c_orig in candidate_lower.items():
                if jd_lower in c_lower or c_lower in jd_lower:
                    substring_match = (c_orig, 0.92)
                    break

            if substring_match:
                results.append(SkillMatch(
                    jd_skill        = jd_skill,
                    candidate_skill = substring_match[0],
                    similarity      = substring_match[1],
                    matched         = True,
                    match_type      = "exact",
                ))
            else:
                remaining.append(jd_skill)

        # Second pass: semantic embedding search for non-exact matches
        if remaining and candidate_skills:
            jd_embs   = embedder.embed_batch(remaining)         # (R, 384)
            c_embs    = embedder.embed_batch(candidate_skills)  # (C, 384)
            sim_matrix = jd_embs @ c_embs.T                     # (R, C)

            import numpy as np
            for i, jd_skill in enumerate(remaining):
                sims     = sim_matrix[i]
                best_idx = int(np.argmax(sims))
                best_sim = float(sims[best_idx])

                if best_sim >= self.STRONG_MATCH_THRESHOLD:
                    match_type = "semantic_strong"
                    matched    = True
                elif best_sim >= self.SEMANTIC_MATCH_THRESHOLD:
                    match_type = "semantic"
                    matched    = True
                else:
                    match_type = "none"
                    matched    = False

                results.append(SkillMatch(
                    jd_skill        = jd_skill,
                    candidate_skill = candidate_skills[best_idx] if matched else "",
                    similarity      = best_sim,
                    matched         = matched,
                    match_type      = match_type,
                ))

                print(f"[SkillMatcher] '{jd_skill}' ↔ '{candidate_skills[best_idx]}' "
                      f"= {best_sim:.3f} ({match_type})")

        # Sort: matched first, then by similarity desc
        results.sort(key=lambda m: (not m.matched, -m.similarity))
        return results

    def compute_skill_coverage(
        self,
        matches: list[SkillMatch],
    ) -> dict:
        """
        Compute summary statistics for a set of skill matches.

        Returns:
            {total, matched, unmatched, coverage_pct, avg_similarity}
        """
        total    = len(matches)
        matched  = sum(1 for m in matches if m.matched)
        avg_sim  = (
            sum(m.similarity for m in matches) / total
            if total > 0 else 0.0
        )
        return {
            "total":        total,
            "matched":      matched,
            "unmatched":    total - matched,
            "coverage_pct": round(matched / total * 100, 1) if total > 0 else 0.0,
            "avg_similarity": round(avg_sim, 3),
        }
