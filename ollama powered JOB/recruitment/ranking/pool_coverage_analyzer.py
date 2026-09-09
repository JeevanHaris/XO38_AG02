"""
RecruitScreen -- Pool Coverage Analyzer
----------------------------------------
Pure Python analysis: for each required skill/experience constraint,
how many candidates in the pool satisfy it? Then compute the intersection.

100% deterministic -- no LLM involved.

Output:
  RequirementCoverage
    .entries            -- per-skill count, pct, and ASCII bar
    .intersection_count -- candidates satisfying ALL requirements
    .has_perfect_match  -- intersection_count > 0
"""

from ..models import (
    JDAnalysis, CandidateScore, VerificationStatus,
    RequirementCoverage, CoverageEntry,
)

import re


_BAR_WIDTH   = 10
_SKILL_PASS  = {VerificationStatus.STRONGLY_SUPPORTED, VerificationStatus.PARTIALLY_SUPPORTED}


def _make_bar(pct: float) -> str:
    """Generate a filled/empty unicode progress bar string."""
    filled = round(pct / 100 * _BAR_WIDTH)
    return "\u2588" * filled + "\u2591" * (_BAR_WIDTH - filled)


def _parse_min_years(exp_str: str) -> float:
    """Extract the minimum experience requirement, e.g. '3-5 years' -> 3.0"""
    if not exp_str:
        return 0.0
    nums = re.findall(r"\d+\.?\d*", exp_str)
    return float(nums[0]) if nums else 0.0


class PoolCoverageAnalyzer:
    """
    Computes per-requirement pool coverage and the ALL-requirements intersection.
    Designed to run immediately after CandidateScorer (Stage 8).
    """

    # Threshold: candidate "has" a skill if similarity or evidence passes this
    SKILL_MATCH_THRESHOLD = 0.55

    def analyze(
        self,
        jd_analysis:  JDAnalysis,
        all_scores:   list[CandidateScore],
    ) -> RequirementCoverage:
        total = len(all_scores)
        if total == 0:
            return RequirementCoverage(total_candidates=0)

        entries = []
        # Track which candidates pass each requirement (for intersection)
        candidate_pass_sets: list[set[str]] = []   # one set per requirement

        # --- Per required skill ---
        for skill in jd_analysis.required_skills:
            passing_ids = set()
            for cs in all_scores:
                if self._candidate_has_skill(cs, skill):
                    passing_ids.add(cs.candidate_id)

            count = len(passing_ids)
            pct   = count / total * 100
            entries.append(CoverageEntry(
                requirement = skill,
                count       = count,
                total       = total,
                percentage  = round(pct, 1),
                bar         = _make_bar(pct),
            ))
            candidate_pass_sets.append(passing_ids)

        # --- Experience requirement ---
        min_years = _parse_min_years(jd_analysis.experience_years)
        if min_years > 0:
            exp_ids = set()
            for cs in all_scores:
                candidate_yrs = (cs.profile.total_experience_years
                                 if cs.profile else 0.0)
                if candidate_yrs >= min_years:
                    exp_ids.add(cs.candidate_id)

            count = len(exp_ids)
            pct   = count / total * 100
            entries.append(CoverageEntry(
                requirement = f"{jd_analysis.experience_years} experience",
                count       = count,
                total       = total,
                percentage  = round(pct, 1),
                bar         = _make_bar(pct),
            ))
            candidate_pass_sets.append(exp_ids)

        # --- Intersection: candidates passing ALL requirements ---
        if candidate_pass_sets:
            all_ids = {cs.candidate_id for cs in all_scores}
            intersection = all_ids
            for pass_set in candidate_pass_sets:
                intersection = intersection & pass_set
            intersection_count = len(intersection)
        else:
            intersection_count = total   # no constraints -> everyone qualifies

        intersection_pct  = intersection_count / total * 100
        has_perfect_match = intersection_count > 0

        print(f"[PoolCoverage] {intersection_count}/{total} candidates satisfy ALL requirements "
              f"({intersection_pct:.0f}%)")

        return RequirementCoverage(
            entries            = entries,
            intersection_count = intersection_count,
            intersection_pct   = round(intersection_pct, 1),
            total_candidates   = total,
            has_perfect_match  = has_perfect_match,
        )

    # --- Helpers -------------------------------------------------------

    def _candidate_has_skill(self, cs: CandidateScore, skill: str) -> bool:
        """
        Returns True if the candidate has sufficient evidence for a skill.
        Checks verification results first, then semantic skill matches.
        """
        # Check evidence verification
        for v in cs.skill_breakdown:
            if self._skill_matches_key(v.jd_skill, skill):
                if v.status in _SKILL_PASS:
                    return True

        # Check semantic skill matches
        for m in cs.skill_matches:
            if self._skill_matches_key(m.jd_skill, skill):
                if m.matched and m.similarity >= self.SKILL_MATCH_THRESHOLD:
                    return True

        return False

    @staticmethod
    def _skill_matches_key(jd_skill: str, target: str) -> bool:
        """Case-insensitive partial match between skill identifiers."""
        return (jd_skill.strip().lower() == target.strip().lower() or
                target.strip().lower() in jd_skill.strip().lower() or
                jd_skill.strip().lower() in target.strip().lower())
