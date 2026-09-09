"""
RecruitScreen v1.0 — Requirement Gap Analyzer
───────────────────────────────────────────────
Analyzes the entire applicant pool to identify skill coverage gaps.

Example output:
  Python         13/15 ✓  ADEQUATE
  FastAPI         9/15 ✓  ADEQUATE
  Docker          6/15 △  MODERATE
  Kubernetes      2/15 ⚠  HIGH_RISK
"""

from ..models import (
    JDAnalysis, CandidateScore, VerificationStatus,
    SkillGap, GapReport, GapRiskLevel,
)


class RequirementGapAnalyzer:
    """
    Analyzes the applicant pool to identify which required skills
    are scarce or missing across all candidates.
    """

    ADEQUATE_THRESHOLD  = 70.0   # >= 70% have the skill → ADEQUATE
    MODERATE_THRESHOLD  = 40.0   # 40-70% → MODERATE risk
    # < 40% → HIGH_RISK

    def analyze(
        self,
        jd_analysis:  JDAnalysis,
        all_scores:   list[CandidateScore],
    ) -> GapReport:
        """
        Build a pool-level skill gap report.

        Args:
            jd_analysis:  Structured JD with required_skills list
            all_scores:   Scored candidates (all, not just top N)

        Returns:
            GapReport with per-skill coverage statistics
        """
        total = len(all_scores)
        if total == 0 or not jd_analysis.required_skills:
            return GapReport(total_candidates=total)

        # Count how many candidates have each required skill
        skill_counts: dict[str, int] = {
            skill: 0 for skill in jd_analysis.required_skills
        }

        for candidate_score in all_scores:
            # Check verification results for each skill
            verif_map = {v.jd_skill: v.status for v in candidate_score.skill_breakdown}

            # Also check semantic skill matches
            match_map = {m.jd_skill: m.matched for m in candidate_score.skill_matches}

            for skill in jd_analysis.required_skills:
                # Has verified evidence OR semantic skill match
                status  = verif_map.get(skill, None)
                matched = match_map.get(skill, False)

                has_skill = (
                    status in (
                        VerificationStatus.STRONGLY_SUPPORTED,
                        VerificationStatus.PARTIALLY_SUPPORTED,
                    )
                    or matched
                )

                if has_skill:
                    skill_counts[skill] += 1

        # Build SkillGap entries
        skill_gaps = []
        for skill in jd_analysis.required_skills:
            count   = skill_counts[skill]
            pct     = (count / total * 100) if total > 0 else 0.0

            if pct >= self.ADEQUATE_THRESHOLD:
                risk = GapRiskLevel.ADEQUATE
            elif pct >= self.MODERATE_THRESHOLD:
                risk = GapRiskLevel.MODERATE
            else:
                risk = GapRiskLevel.HIGH_RISK

            skill_gaps.append(SkillGap(
                skill            = skill,
                count_with_skill = count,
                total_candidates = total,
                percentage       = round(pct, 1),
                risk_level       = risk,
            ))

        # Sort: high risk first, then by coverage ascending
        skill_gaps.sort(key=lambda g: (
            0 if g.risk_level == GapRiskLevel.HIGH_RISK else
            1 if g.risk_level == GapRiskLevel.MODERATE else 2,
            g.percentage,
        ))

        high_risk_skills = [
            g.skill for g in skill_gaps
            if g.risk_level == GapRiskLevel.HIGH_RISK
        ]

        summary = self._generate_summary(skill_gaps, total, high_risk_skills)

        print(f"[GapAnalyzer] {len(high_risk_skills)} high-risk skill gaps "
              f"in pool of {total} candidates")

        return GapReport(
            skill_gaps        = skill_gaps,
            total_candidates  = total,
            high_risk_skills  = high_risk_skills,
            summary           = summary,
        )

    @staticmethod
    def _generate_summary(
        gaps:             list[SkillGap],
        total:            int,
        high_risk_skills: list[str],
    ) -> str:
        """Generate a human-readable summary of the gap analysis."""
        if not gaps:
            return "No gap data available."

        adequate = sum(1 for g in gaps if g.risk_level == GapRiskLevel.ADEQUATE)
        moderate = sum(1 for g in gaps if g.risk_level == GapRiskLevel.MODERATE)
        high     = len(high_risk_skills)

        parts = [
            f"Analyzed {total} candidates across {len(gaps)} required skills."
        ]

        if adequate > 0:
            parts.append(f"{adequate} skills have good pool coverage (≥70%).")
        if moderate > 0:
            parts.append(f"{moderate} skills have moderate pool coverage (40-70%).")
        if high > 0:
            skills_str = ", ".join(high_risk_skills[:3])
            if len(high_risk_skills) > 3:
                skills_str += f" and {len(high_risk_skills) - 3} more"
            parts.append(
                f"⚠ {high} skills are high-risk gaps (<40% coverage): {skills_str}."
            )

        return " ".join(parts)
