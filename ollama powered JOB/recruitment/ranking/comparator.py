"""
RecruitScreen v1.0 — Candidate Comparator
───────────────────────────────────────────
Ranks all scored candidates and generates LLM trade-off narratives.
"""

from ..models import (
    CandidateScore, RankedCandidate, RankedList, JDAnalysis,
    VerificationStatus,
)


TRADEOFF_SYSTEM = """You are an expert technical recruiter writing concise candidate trade-off notes.
Be specific about strengths and weaknesses. 2-3 sentences max. No fluff."""


TRADEOFF_PROMPT = """Write a 2-3 sentence trade-off note for these two candidates being compared for: {role}

Candidate A: {name_a} (Score: {score_a}/100)
- Strong skills: {strong_a}
- Missing/weak: {weak_a}

Candidate B: {name_b} (Score: {score_b}/100)
- Strong skills: {strong_b}
- Missing/weak: {weak_b}

Write a concise trade-off: when would you pick A over B and vice versa?"""


class CandidateComparator:
    """Ranks candidates and generates trade-off narratives."""

    def __init__(self, gateway=None, router=None):
        self.gateway = gateway
        self.router  = router

    def rank(
        self,
        scores:      list[CandidateScore],
        jd_analysis: JDAnalysis,
    ) -> RankedList:
        """
        Sort candidates by total_score and produce a RankedList.
        Generates trade-off note for top candidates (top 5).
        """
        if not scores:
            return RankedList(jd_role=jd_analysis.role_title, total_analyzed=0)

        # Sort descending by total score
        sorted_scores = sorted(scores, key=lambda s: s.total_score, reverse=True)

        ranked = []
        for i, score in enumerate(sorted_scores):
            # Generate trade-off vs next candidate (for top 5)
            tradeoff = ""
            if (
                i < min(5, len(sorted_scores) - 1)
                and self.gateway
                and i == 0
            ):
                # Only generate trade-off for #1 vs #2 (costly for large pools)
                tradeoff = self._generate_tradeoff(
                    sorted_scores[0],
                    sorted_scores[1],
                    jd_analysis,
                )

            ranked.append(RankedCandidate(
                rank          = i + 1,
                score         = score,
                tradeoff_note = tradeoff,
            ))

        print(f"[Comparator] Ranked {len(ranked)} candidates. "
              f"Top: {sorted_scores[0].candidate_name} ({sorted_scores[0].total_score:.1f})")

        return RankedList(
            candidates    = ranked,
            jd_role       = jd_analysis.role_title,
            total_analyzed = len(scores),
        )

    def generate_comparison(
        self,
        score_a:     CandidateScore,
        score_b:     CandidateScore,
        jd_analysis: JDAnalysis,
    ) -> dict:
        """
        Generate a detailed comparison between two candidates.
        Used by the frontend's Compare view.
        """
        tradeoff = self._generate_tradeoff(score_a, score_b, jd_analysis)

        # Skill-by-skill comparison
        skill_comparison = self._compare_skills(score_a, score_b)

        return {
            "candidate_a":      score_a.to_dict(),
            "candidate_b":      score_b.to_dict(),
            "tradeoff":         tradeoff,
            "skill_comparison": skill_comparison,
            "recommendation":   self._recommendation(score_a, score_b),
        }

    # ── Private ───────────────────────────────────────────────────────

    def _generate_tradeoff(
        self,
        score_a:     CandidateScore,
        score_b:     CandidateScore,
        jd_analysis: JDAnalysis,
    ) -> str:
        """Generate a 2-3 sentence trade-off narrative via Groq."""
        if not self.gateway:
            return self._rule_based_tradeoff(score_a, score_b)

        try:
            decision = self.router.route(
                "compare candidates trade-off analysis",
                task_type_hint="comparison",
            )

            strong_a = self._get_strong_skills(score_a)
            weak_a   = self._get_weak_skills(score_a)
            strong_b = self._get_strong_skills(score_b)
            weak_b   = self._get_weak_skills(score_b)

            prompt = TRADEOFF_PROMPT.format(
                role    = jd_analysis.role_title or "this position",
                name_a  = score_a.candidate_name,
                score_a = score_a.total_score,
                strong_a = ", ".join(strong_a[:4]) or "N/A",
                weak_a   = ", ".join(weak_a[:3])   or "None",
                name_b  = score_b.candidate_name,
                score_b = score_b.total_score,
                strong_b = ", ".join(strong_b[:4]) or "N/A",
                weak_b   = ", ".join(weak_b[:3])   or "None",
            )

            response = self.gateway.call(
                decision.model,
                [
                    {"role": "system", "content": TRADEOFF_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                provider=decision.provider,
            )
            return response.content.strip()

        except Exception as e:
            print(f"[Comparator] Trade-off generation error: {e}")
            return self._rule_based_tradeoff(score_a, score_b)

    @staticmethod
    def _rule_based_tradeoff(a: CandidateScore, b: CandidateScore) -> str:
        """Simple rule-based trade-off when LLM is unavailable."""
        diff = abs(a.total_score - b.total_score)
        if diff < 5:
            return (
                f"{a.candidate_name} and {b.candidate_name} are closely matched "
                f"({a.total_score:.0f} vs {b.total_score:.0f}). "
                f"Review individual skill evidence to make the final call."
            )
        winner = a if a.total_score > b.total_score else b
        loser  = b if winner is a else a
        return (
            f"{winner.candidate_name} scores higher overall ({winner.total_score:.0f} vs "
            f"{loser.total_score:.0f}). "
            f"Review the skill evidence breakdown for a detailed comparison."
        )

    @staticmethod
    def _compare_skills(a: CandidateScore, b: CandidateScore) -> list[dict]:
        """Build a skill-by-skill comparison table."""
        # Build lookup maps: jd_skill → VerificationResult
        def build_map(score: CandidateScore) -> dict:
            return {v.jd_skill: v for v in score.skill_breakdown}

        map_a = build_map(a)
        map_b = build_map(b)

        # Union of all skills
        all_skills = sorted(set(map_a.keys()) | set(map_b.keys()))

        rows = []
        for skill in all_skills:
            va = map_a.get(skill)
            vb = map_b.get(skill)
            rows.append({
                "skill":      skill,
                "candidate_a": {
                    "status": va.status.value      if va else "NOT_MENTIONED",
                    "icon":   va.status_icon        if va else "⚪",
                    "explanation": va.explanation  if va else "",
                },
                "candidate_b": {
                    "status": vb.status.value      if vb else "NOT_MENTIONED",
                    "icon":   vb.status_icon        if vb else "⚪",
                    "explanation": vb.explanation  if vb else "",
                },
            })
        return rows

    @staticmethod
    def _get_strong_skills(score: CandidateScore) -> list[str]:
        return [
            v.jd_skill for v in score.skill_breakdown
            if v.status == VerificationStatus.STRONGLY_SUPPORTED
        ]

    @staticmethod
    def _get_weak_skills(score: CandidateScore) -> list[str]:
        return [
            v.jd_skill for v in score.skill_breakdown
            if v.status in (
                VerificationStatus.NOT_MENTIONED,
                VerificationStatus.UNSUPPORTED,
            )
        ]

    @staticmethod
    def _recommendation(a: CandidateScore, b: CandidateScore) -> str:
        if a.total_score > b.total_score + 5:
            return f"Recommend {a.candidate_name}"
        elif b.total_score > a.total_score + 5:
            return f"Recommend {b.candidate_name}"
        else:
            return "Too close to call — review evidence details"
