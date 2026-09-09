"""
RecruitScreen v1.0 — Deterministic Candidate Scorer
─────────────────────────────────────────────────────
Python-based scoring engine. No LLM randomness in final scores.

Scoring Weights:
  Required Skills Coverage   40%
  Relevant Experience        25%
  Evidence Strength          20%
  Preferred Skills           10%
  Education Match             5%
"""

from ..models import (
    JDAnalysis, CandidateProfile, VerificationResult, VerificationStatus,
    SkillMatch, CandidateScore, ComponentScore, GitHubEvidenceStatus,
)


# ─── Weight Configuration ─────────────────────────────────────────────

SCORE_WEIGHTS = {
    "required_skills":    0.40,
    "experience":         0.25,
    "evidence_strength":  0.20,
    "preferred_skills":   0.10,
    "education":          0.05,
}

# Evidence strength scores (0-1 scale)
EVIDENCE_SCORES = {
    VerificationStatus.STRONGLY_SUPPORTED:  1.0,
    VerificationStatus.PARTIALLY_SUPPORTED: 0.6,
    VerificationStatus.UNSUPPORTED:         0.1,
    VerificationStatus.NOT_MENTIONED:       0.0,
}


class CandidateScorer:
    """
    Deterministic scoring engine for a single candidate against a JD.
    All scoring is pure Python math — no LLM involved.
    """

    def __init__(self, weights: dict = None):
        self.weights = weights or SCORE_WEIGHTS

    def score(
        self,
        profile:         CandidateProfile,
        jd_analysis:     JDAnalysis,
        verifications:   list[VerificationResult],
        skill_matches:   list[SkillMatch],
        pref_matches:    list[SkillMatch] = None,
    ) -> CandidateScore:
        """
        Compute a CandidateScore from all pipeline outputs.

        Args:
            profile:       Candidate's profile
            jd_analysis:   Structured JD requirements
            verifications: Evidence verification results (per required skill)
            skill_matches: Semantic skill matches (required skills)
            pref_matches:  Semantic skill matches (preferred skills, optional)

        Returns:
            CandidateScore with total_score and per-component breakdown
        """
        components = []

        # ── Component 1: Required Skills Coverage ────────────────────
        req_score, req_detail = self._score_required_skills(
            skill_matches, verifications, jd_analysis
        )
        components.append(ComponentScore(
            name     = "Required Skills",
            score    = req_score,
            weight   = self.weights["required_skills"],
            weighted = req_score * self.weights["required_skills"],
            detail   = req_detail,
        ))

        # ── Component 2: Experience ───────────────────────────────────
        exp_score, exp_detail = self._score_experience(profile, jd_analysis)
        components.append(ComponentScore(
            name     = "Relevant Experience",
            score    = exp_score,
            weight   = self.weights["experience"],
            weighted = exp_score * self.weights["experience"],
            detail   = exp_detail,
        ))

        # ── Component 3: Evidence Strength ────────────────────────────
        ev_score, ev_detail = self._score_evidence_strength(verifications)
        components.append(ComponentScore(
            name     = "Evidence Strength",
            score    = ev_score,
            weight   = self.weights["evidence_strength"],
            weighted = ev_score * self.weights["evidence_strength"],
            detail   = ev_detail,
        ))

        # ── Component 4: Preferred Skills ────────────────────────────
        pref_score, pref_detail = self._score_preferred_skills(pref_matches or [])
        components.append(ComponentScore(
            name     = "Preferred Skills",
            score    = pref_score,
            weight   = self.weights["preferred_skills"],
            weighted = pref_score * self.weights["preferred_skills"],
            detail   = pref_detail,
        ))

        # ── Component 5: Education ────────────────────────────────────
        edu_score, edu_detail = self._score_education(profile, jd_analysis)
        components.append(ComponentScore(
            name     = "Education",
            score    = edu_score,
            weight   = self.weights["education"],
            weighted = edu_score * self.weights["education"],
            detail   = edu_detail,
        ))

        # ── Total Score ───────────────────────────────────────────────
        total = sum(c.weighted for c in components) * 100   # 0–100 scale

        return CandidateScore(
            candidate_id     = profile.candidate_id,
            candidate_name   = profile.name,
            total_score      = round(total, 1),
            component_scores = components,
            skill_breakdown  = verifications,
            skill_matches    = skill_matches,
            profile          = profile,
        )

    # ── Component Scorers ─────────────────────────────────────────────

    @staticmethod
    def _score_required_skills(
        matches:       list[SkillMatch],
        verifications: list[VerificationResult],
        jd_analysis:   JDAnalysis,
    ) -> tuple[float, str]:
        """
        Score based on what fraction of required skills the candidate has.
        Gives partial credit for semantic matches.
        """
        if not jd_analysis.required_skills:
            return 0.8, "No required skills specified"

        total = len(jd_analysis.required_skills)
        if not matches:
            return 0.0, f"0/{total} required skills matched"

        # Map jd_skill → best match score
        match_scores = {}
        for m in matches:
            key = m.jd_skill
            if m.matched:
                match_scores[key] = min(m.similarity, 1.0)
            else:
                match_scores[key] = 0.0

        # Merge verification results — strongly verified bumps score
        verif_map = {v.jd_skill: v for v in verifications}
        for skill, verif in verif_map.items():
            if verif.status == VerificationStatus.STRONGLY_SUPPORTED:
                match_scores[skill] = max(match_scores.get(skill, 0), 0.95)
            elif verif.status == VerificationStatus.PARTIALLY_SUPPORTED:
                match_scores[skill] = max(match_scores.get(skill, 0), 0.55)

        if not match_scores:
            return 0.0, f"0/{total} required skills matched"

        avg_score  = sum(match_scores.values()) / total
        n_matched  = sum(1 for s in match_scores.values() if s >= 0.55)
        detail     = f"{n_matched}/{total} required skills matched"

        return round(avg_score, 4), detail

    @staticmethod
    def _score_experience(
        profile:     CandidateProfile,
        jd_analysis: JDAnalysis,
    ) -> tuple[float, str]:
        """
        Score based on years of experience vs JD requirement.
        """
        candidate_years = profile.total_experience_years

        # Parse JD experience requirement
        import re
        exp_str = jd_analysis.experience_years or ""
        nums    = re.findall(r"\d+\.?\d*", exp_str)

        if not nums:
            # No experience requirement — give base score based on seniority signals
            if candidate_years >= 5:
                score = 0.9
            elif candidate_years >= 2:
                score = 0.75
            elif candidate_years >= 0.5:
                score = 0.55
            else:
                score = 0.40
            return score, f"{candidate_years:.1f} years experience"

        required_min = float(nums[0])
        required_max = float(nums[-1]) if len(nums) > 1 else required_min * 1.5

        if candidate_years >= required_max:
            score  = 1.0
            detail = f"{candidate_years:.1f}y ≥ {required_max:.0f}y required (over-qualified/senior)"
        elif candidate_years >= required_min:
            # Linearly interpolate within range
            score  = 0.7 + 0.3 * ((candidate_years - required_min) / max(required_max - required_min, 1))
            detail = f"{candidate_years:.1f}y meets {required_min:.0f}-{required_max:.0f}y requirement"
        elif candidate_years >= required_min * 0.6:
            score  = 0.5
            detail = f"{candidate_years:.1f}y slightly below {required_min:.0f}y minimum"
        else:
            score  = max(0.15, candidate_years / required_min) if required_min > 0 else 0.15
            detail = f"{candidate_years:.1f}y below {required_min:.0f}y minimum"

        return round(score, 4), detail

    @staticmethod
    def _score_evidence_strength(
        verifications: list[VerificationResult],
    ) -> tuple[float, str]:
        """
        Score based on overall evidence quality across all verified claims.
        GitHub evidence boost:
          - SUPPORTED GitHub + PARTIALLY_SUPPORTED resume → treated as STRONGLY_SUPPORTED
          - SUPPORTED GitHub + already STRONGLY_SUPPORTED  → small confidence boost
          - UNVERIFIED GitHub → neutral (no penalty; absence ≠ absence of skill)
        """
        if not verifications:
            return 0.5, "No verification data available"

        total_weight  = 0.0
        total_score   = 0.0
        github_boosts = 0

        for v in verifications:
            base_ev_score = EVIDENCE_SCORES.get(v.status, 0.0)
            ev_score      = base_ev_score

            # Apply GitHub evidence boost (never penalise UNVERIFIED)
            if v.github_result and v.github_result.status != GitHubEvidenceStatus.UNVERIFIED:
                if v.github_result.status == GitHubEvidenceStatus.SUPPORTED:
                    if v.status == VerificationStatus.PARTIALLY_SUPPORTED:
                        # Corroborated externally — uplift to strongly-supported level
                        ev_score = EVIDENCE_SCORES[VerificationStatus.STRONGLY_SUPPORTED]
                        github_boosts += 1
                    elif v.status == VerificationStatus.STRONGLY_SUPPORTED:
                        # Already strong — small confidence bump (cap at 1.0)
                        ev_score = min(1.0, base_ev_score + 0.05)
                        github_boosts += 1
                elif v.github_result.status == GitHubEvidenceStatus.PARTIAL:
                    # Partial GitHub evidence — minor boost only if currently NOT_MENTIONED
                    if v.status == VerificationStatus.NOT_MENTIONED:
                        ev_score = EVIDENCE_SCORES[VerificationStatus.PARTIALLY_SUPPORTED] * 0.5
                        github_boosts += 1

            weight        = v.confidence_score if v.confidence_score > 0 else 0.5
            total_score  += ev_score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.5, "Inconclusive evidence"

        avg      = total_score / total_weight
        strongly = sum(1 for v in verifications
                       if v.status == VerificationStatus.STRONGLY_SUPPORTED)
        partial  = sum(1 for v in verifications
                       if v.status == VerificationStatus.PARTIALLY_SUPPORTED)
        boost_note = f", +{github_boosts} GitHub boost(s)" if github_boosts else ""
        detail     = f"{strongly} strong, {partial} partial evidence{boost_note}"

        return round(avg, 4), detail

    @staticmethod
    def _score_preferred_skills(
        pref_matches: list[SkillMatch],
    ) -> tuple[float, str]:
        """Score preferred skill coverage (0–1)."""
        if not pref_matches:
            return 0.5, "No preferred skills specified"

        total   = len(pref_matches)
        matched = sum(1 for m in pref_matches if m.matched)
        score   = matched / total if total > 0 else 0.5
        detail  = f"{matched}/{total} preferred skills matched"

        return round(score, 4), detail

    @staticmethod
    def _score_education(
        profile:     CandidateProfile,
        jd_analysis: JDAnalysis,
    ) -> tuple[float, str]:
        """Heuristic education match score."""
        if not jd_analysis.education:
            return 0.8, "No education requirement specified"

        if not profile.education:
            return 0.3, "No education info on resume"

        # Simple keyword matching
        req_keywords = set()
        for req in jd_analysis.education:
            req_keywords.update(req.lower().split())

        candidate_edu_text = " ".join(profile.education).lower()
        matches = sum(1 for kw in req_keywords if kw in candidate_edu_text
                      and len(kw) > 3)

        if matches == 0:
            return 0.4, "Education requirements not met"
        elif matches >= 2:
            return 0.9, "Education requirements met"
        else:
            return 0.65, "Education partially meets requirements"
