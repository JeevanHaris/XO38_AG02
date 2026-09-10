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
        score_a,
        score_b,
        jd_analysis,
    ) -> dict:
        """
        Generate a detailed comparison between two candidates.
        Used by the frontend's Compare view.
        """
        name_a = score_a.get("candidate_name") if isinstance(score_a, dict) else getattr(score_a, "candidate_name", "Candidate A")
        name_b = score_b.get("candidate_name") if isinstance(score_b, dict) else getattr(score_b, "candidate_name", "Candidate B")
        tot_a  = score_a.get("total_score", 0.0) if isinstance(score_a, dict) else getattr(score_a, "total_score", 0.0)
        tot_b  = score_b.get("total_score", 0.0) if isinstance(score_b, dict) else getattr(score_b, "total_score", 0.0)

        # Extract experience
        if isinstance(score_a, dict):
            exp_a = score_a.get("profile", {}).get("total_experience_years") or score_a.get("relevant_years", 0.0) or 0.0
        else:
            prof_a = getattr(score_a, "profile", None)
            exp_a = getattr(prof_a, "total_experience_years", 0.0) if prof_a else 0.0

        if isinstance(score_b, dict):
            exp_b = score_b.get("profile", {}).get("total_experience_years") or score_b.get("relevant_years", 0.0) or 0.0
        else:
            prof_b = getattr(score_b, "profile", None)
            exp_b = getattr(prof_b, "total_experience_years", 0.0) if prof_b else 0.0

        tradeoff = self._generate_tradeoff(score_a, score_b, jd_analysis)
        skill_comparison = self._compare_skills(score_a, score_b)
        rec = self._recommendation(score_a, score_b)

        if tot_a > tot_b:
            winner = name_a
        elif tot_b > tot_a:
            winner = name_b
        else:
            winner = "Tie"

        dict_a = score_a if isinstance(score_a, dict) else score_a.to_dict()
        dict_b = score_b if isinstance(score_b, dict) else score_b.to_dict()

        return {
            "candidate_a":        dict_a,
            "candidate_b":        dict_b,
            "candidate_a_name":   name_a,
            "candidate_b_name":   name_b,
            "candidate_a_score":  round(float(tot_a), 1),
            "candidate_b_score":  round(float(tot_b), 1),
            "candidate_a_exp":    round(float(exp_a), 1),
            "candidate_b_exp":    round(float(exp_b), 1),
            "tradeoff":           tradeoff,
            "narrative":          tradeoff,
            "winner":             winner,
            "recommendation":     rec,
            "skill_comparison":   skill_comparison,
        }

    # ── Private ───────────────────────────────────────────────────────

    def _generate_tradeoff(
        self,
        score_a,
        score_b,
        jd_analysis,
    ) -> str:
        """Generate a 2-3 sentence trade-off narrative via Groq."""
        if not self.gateway:
            return self._rule_based_tradeoff(score_a, score_b)

        try:
            decision = self.router.route(
                "compare candidates trade-off analysis",
                task_type_hint="comparison",
            )

            name_a = score_a.get("candidate_name") if isinstance(score_a, dict) else getattr(score_a, "candidate_name", "Candidate A")
            name_b = score_b.get("candidate_name") if isinstance(score_b, dict) else getattr(score_b, "candidate_name", "Candidate B")
            tot_a  = score_a.get("total_score", 0.0) if isinstance(score_a, dict) else getattr(score_a, "total_score", 0.0)
            tot_b  = score_b.get("total_score", 0.0) if isinstance(score_b, dict) else getattr(score_b, "total_score", 0.0)

            strong_a = self._get_strong_skills(score_a)
            weak_a   = self._get_weak_skills(score_a)
            strong_b = self._get_strong_skills(score_b)
            weak_b   = self._get_weak_skills(score_b)

            role_title = ""
            if jd_analysis:
                if isinstance(jd_analysis, dict):
                    role_title = jd_analysis.get("role_title", "")
                else:
                    role_title = getattr(jd_analysis, "role_title", "")

            prompt = TRADEOFF_PROMPT.format(
                role     = role_title or "this position",
                name_a   = name_a,
                score_a  = tot_a,
                strong_a = ", ".join(strong_a[:4]) or "N/A",
                weak_a   = ", ".join(weak_a[:3])   or "None",
                name_b   = name_b,
                score_b  = tot_b,
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
    def _rule_based_tradeoff(a, b) -> str:
        """Simple rule-based trade-off when LLM is unavailable."""
        name_a = a.get("candidate_name") if isinstance(a, dict) else getattr(a, "candidate_name", "Candidate A")
        name_b = b.get("candidate_name") if isinstance(b, dict) else getattr(b, "candidate_name", "Candidate B")
        tot_a  = a.get("total_score", 0.0) if isinstance(a, dict) else getattr(a, "total_score", 0.0)
        tot_b  = b.get("total_score", 0.0) if isinstance(b, dict) else getattr(b, "total_score", 0.0)

        diff = abs(tot_a - tot_b)
        if diff < 5:
            return (
                f"{name_a} and {name_b} are closely matched "
                f"({tot_a:.0f} vs {tot_b:.0f}). "
                f"Review individual skill evidence to make the final call."
            )
        winner_name  = name_a if tot_a > tot_b else name_b
        winner_score = tot_a if tot_a > tot_b else tot_b
        loser_score  = tot_b if tot_a > tot_b else tot_a
        return (
            f"{winner_name} scores higher overall ({winner_score:.0f} vs "
            f"{loser_score:.0f}). "
            f"Review the skill evidence breakdown for a detailed comparison."
        )

    @staticmethod
    def _compare_skills(a, b) -> list[dict]:
        """Build a skill-by-skill comparison table."""
        def build_map(score) -> dict:
            if isinstance(score, dict):
                breakdown = score.get("skill_breakdown") or []
            else:
                breakdown = getattr(score, "skill_breakdown", []) or []

            out = {}
            for v in breakdown:
                if isinstance(v, dict):
                    skill_name = v.get("jd_skill") or v.get("skill")
                    if skill_name:
                        out[skill_name] = v
                else:
                    skill_name = getattr(v, "jd_skill", None) or getattr(v, "skill", None)
                    if skill_name:
                        out[skill_name] = v
            return out

        map_a = build_map(a)
        map_b = build_map(b)

        # Union of all skills
        all_skills = sorted(set(map_a.keys()) | set(map_b.keys()))

        weight_map = {
            "STRONGLY_SUPPORTED": 3,
            "PARTIALLY_SUPPORTED": 2,
            "UNSUPPORTED": 1,
            "NOT_MENTIONED": 0,
        }

        icon_map = {
            "STRONGLY_SUPPORTED": "🟢",
            "PARTIALLY_SUPPORTED": "🟡",
            "UNSUPPORTED": "🔴",
            "NOT_MENTIONED": "⚪",
        }

        def extract_status_info(v):
            if not v:
                return "NOT_MENTIONED", "⚪", ""
            if isinstance(v, dict):
                raw_st = v.get("status", "NOT_MENTIONED")
                status_str = raw_st.value if hasattr(raw_st, "value") else str(raw_st)
                icon = v.get("status_icon") or icon_map.get(status_str, "⚪")
                explanation = v.get("explanation") or ""
                return status_str, icon, explanation

            raw_st = getattr(v, "status", "NOT_MENTIONED")
            status_str = raw_st.value if hasattr(raw_st, "value") else str(raw_st)
            icon = getattr(v, "status_icon", None) or icon_map.get(status_str, "⚪")
            explanation = getattr(v, "explanation", "") or ""
            return status_str, icon, explanation

        rows = []
        for skill in all_skills:
            status_a, icon_a, exp_a = extract_status_info(map_a.get(skill))
            status_b, icon_b, exp_b = extract_status_info(map_b.get(skill))

            wa = weight_map.get(status_a, 0)
            wb = weight_map.get(status_b, 0)
            favors = "A" if wa > wb else ("B" if wb > wa else "")

            rows.append({
                "skill":    skill,
                "a_status": status_a,
                "b_status": status_b,
                "favors":   favors,
                "candidate_a": {
                    "status":      status_a,
                    "icon":        icon_a,
                    "explanation": exp_a,
                },
                "candidate_b": {
                    "status":      status_b,
                    "icon":        icon_b,
                    "explanation": exp_b,
                },
            })
        return rows

    @staticmethod
    def _get_strong_skills(score) -> list[str]:
        breakdown = score.get("skill_breakdown") if isinstance(score, dict) else getattr(score, "skill_breakdown", [])
        strong = []
        for v in (breakdown or []):
            if isinstance(v, dict):
                st = v.get("status")
                st_val = st.value if hasattr(st, "value") else str(st)
                if st_val == "STRONGLY_SUPPORTED":
                    strong.append(v.get("jd_skill") or v.get("skill", ""))
            else:
                st = getattr(v, "status", None)
                st_val = st.value if hasattr(st, "value") else str(st)
                if st_val == "STRONGLY_SUPPORTED":
                    strong.append(getattr(v, "jd_skill", "") or getattr(v, "skill", ""))
        return [s for s in strong if s]

    @staticmethod
    def _get_weak_skills(score) -> list[str]:
        breakdown = score.get("skill_breakdown") if isinstance(score, dict) else getattr(score, "skill_breakdown", [])
        weak = []
        for v in (breakdown or []):
            if isinstance(v, dict):
                st = v.get("status")
                st_val = st.value if hasattr(st, "value") else str(st)
                if st_val in ("NOT_MENTIONED", "UNSUPPORTED"):
                    weak.append(v.get("jd_skill") or v.get("skill", ""))
            else:
                st = getattr(v, "status", None)
                st_val = st.value if hasattr(st, "value") else str(st)
                if st_val in ("NOT_MENTIONED", "UNSUPPORTED"):
                    weak.append(getattr(v, "jd_skill", "") or getattr(v, "skill", ""))
        return [s for s in weak if s]

    @staticmethod
    def _recommendation(a, b) -> str:
        name_a  = a.get("candidate_name") if isinstance(a, dict) else getattr(a, "candidate_name", "Candidate A")
        name_b  = b.get("candidate_name") if isinstance(b, dict) else getattr(b, "candidate_name", "Candidate B")
        score_a = a.get("total_score", 0.0) if isinstance(a, dict) else getattr(a, "total_score", 0.0)
        score_b = b.get("total_score", 0.0) if isinstance(b, dict) else getattr(b, "total_score", 0.0)

        if score_a > score_b + 5:
            return f"Recommend {name_a}"
        elif score_b > score_a + 5:
            return f"Recommend {name_b}"
        else:
            return "Too close to call — review evidence details"
