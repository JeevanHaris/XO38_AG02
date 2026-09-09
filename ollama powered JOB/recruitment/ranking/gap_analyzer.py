"""
RecruitScreen / ARIA Core — Requirement Gap Analyzer
────────────────────────────────────────────────────
Pool-level analysis of skill coverage gaps across all candidates.

1. Python calculates pool counts & percentages:
   Python      13/15  86%  ADEQUATE
   JavaScript  12/15  80%  ADEQUATE
   React        7/15  46%  MODERATE
   Docker       4/15  26%  HIGH_RISK

2. Groq generates concise explanation:
   "React and Docker are significant gaps in the current applicant pool."
"""

from ..models import (
    JDAnalysis, CandidateScore, VerificationStatus,
    SkillGap, GapReport, GapRiskLevel,
)


class RequirementGapAnalyzer:
    """
    Analyzes applicant pool skill coverage and optionally generates Groq narrative.
    """

    ADEQUATE_THRESHOLD = 70.0   # >= 70% -> ADEQUATE
    MODERATE_THRESHOLD = 40.0   # 40-70% -> MODERATE risk
                                # < 40%  -> HIGH_RISK

    def __init__(self, gateway=None, router=None):
        self.gateway = gateway
        self.router  = router

    def analyze(
        self,
        jd_analysis:  JDAnalysis,
        all_scores:   list[CandidateScore],
    ) -> GapReport:
        total = len(all_scores)
        if total == 0 or not jd_analysis.required_skills:
            return GapReport(total_candidates=total)

        # Pure Python calculation
        skill_counts: dict[str, int] = {
            skill: 0 for skill in jd_analysis.required_skills
        }

        for candidate_score in all_scores:
            verif_map = {v.jd_skill: v.status for v in candidate_score.skill_breakdown}
            match_map = {m.jd_skill: m.matched for m in candidate_score.skill_matches}

            for skill in jd_analysis.required_skills:
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

        skill_gaps = []
        for skill in jd_analysis.required_skills:
            count = skill_counts[skill]
            pct   = (count / total * 100) if total > 0 else 0.0

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

        # Sort: high risk first, then lowest percentage
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

        # Optional Groq narrative explanation
        if self.gateway and high_risk_skills:
            try:
                groq_summary = self._generate_groq_explanation(skill_gaps, total, high_risk_skills)
                if groq_summary:
                    summary = groq_summary
            except Exception as e:
                print(f"[GapAnalyzer] Groq explanation fallback: {e}")

        print(f"[GapAnalyzer] {len(high_risk_skills)} high-risk skill gaps in pool of {total} candidates")

        return GapReport(
            skill_gaps       = skill_gaps,
            total_candidates = total,
            high_risk_skills = high_risk_skills,
            summary          = summary,
        )

    def _generate_groq_explanation(
        self,
        gaps: list[SkillGap],
        total: int,
        high_risk_skills: list[str]
    ) -> str:
        decision = self.router.route(
            "explain skill gap analysis",
            task_type_hint="complex_requirement_gap_reasoning"
        )
        gap_lines = [f"- {g.skill}: {g.count_with_skill}/{total} candidates ({g.percentage:.0f}%)" for g in gaps]
        prompt = (
            f"Analyze this talent pool requirement coverage for a hiring manager:\n"
            + "\n".join(gap_lines) + "\n\n"
            "Provide a 2-sentence executive summary highlighting the most critical skill shortages."
        )
        response = self.gateway.call(
            decision.model,
            [
                {"role": "system", "content": "You are a talent acquisition strategist. Be concise and actionable."},
                {"role": "user", "content": prompt}
            ],
            provider=decision.provider
        )
        return response.content.strip()

    @staticmethod
    def _generate_summary(
        gaps:             list[SkillGap],
        total:            int,
        high_risk_skills: list[str],
    ) -> str:
        if not gaps:
            return "No gap data available."

        adequate = sum(1 for g in gaps if g.risk_level == GapRiskLevel.ADEQUATE)
        moderate = sum(1 for g in gaps if g.risk_level == GapRiskLevel.MODERATE)
        high     = len(high_risk_skills)

        parts = [f"Analyzed {total} candidates across {len(gaps)} required skills."]
        if adequate > 0:
            parts.append(f"{adequate} skills have strong pool coverage (≥70%).")
        if moderate > 0:
            parts.append(f"{moderate} skills have moderate pool coverage (40-70%).")
        if high > 0:
            skills_str = ", ".join(high_risk_skills[:3])
            if len(high_risk_skills) > 3:
                skills_str += f" and {len(high_risk_skills) - 3} more"
            parts.append(f"⚠ Critical shortages identified in {skills_str}.")

        return " ".join(parts)
