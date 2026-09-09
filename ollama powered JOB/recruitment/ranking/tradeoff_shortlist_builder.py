"""
RecruitScreen -- Trade-Off Shortlist Builder
---------------------------------------------
When no candidate satisfies ALL requirements (intersection_count == 0),
this builder finds those requiring the fewest compromises and generates
a human-readable trade-off shortlist.

Algorithm:
  Step 1 (Python) -- Annotate each candidate with met / partial / unmet
  Step 2 (Python) -- Sort by unmet_count ascending, then total_score descending
  Step 3 (Groq)   -- Generate a 2-3 sentence trade-off narrative for top N

Language policy:
  * Never say a candidate "lied" or "misrepresented".
  * Use: "The claim is insufficiently supported by available evidence."
  * Frame unmet requirements as gaps, not deceptions.
"""

import re
from ..models import (
    JDAnalysis, CandidateScore, RequirementCoverage,
    FeasibilityShortlist, TradeOffCandidate,
    VerificationStatus,
)


_GROQ_TOP_N   = 5     # Max candidates to generate Groq narratives for
_SKILL_PASS   = {VerificationStatus.STRONGLY_SUPPORTED, VerificationStatus.PARTIALLY_SUPPORTED}
_SKILL_STRONG = {VerificationStatus.STRONGLY_SUPPORTED}
_MATCH_THRESH = 0.55


TRADEOFF_SYSTEM = """You are a senior technical recruiter writing concise, factual candidate
trade-off notes. Be specific about what each candidate brings and what they are missing.
2-3 sentences per candidate. No fluff. Do not use accusatory language."""


TRADEOFF_PROMPT = """For the role of {role}, write a concise trade-off note for each candidate.
No candidate satisfies all requirements. Focus on which requirements each candidate meets
and which they fall short of, so a recruiter can make an informed decision.

Candidates (sorted by fewest missing requirements first):
{candidate_summaries}

Write one trade-off paragraph per candidate in this JSON format:
[
  {{
    "candidate_id": "<id>",
    "tradeoff_note": "<2-3 sentence note>"
  }}
]

Output ONLY valid JSON."""


class TradeOffShortlistBuilder:
    """
    Builds a compromise-aware shortlist when no perfect match exists.
    Uses pure Python to rank + annotate, Groq only for narrative generation.
    """

    def __init__(self, gateway=None, router=None):
        self.gateway = gateway
        self.router  = router

    def build(
        self,
        all_scores:   list[CandidateScore],
        jd_analysis:  JDAnalysis,
        coverage:     RequirementCoverage,
    ) -> FeasibilityShortlist:
        if not all_scores:
            return FeasibilityShortlist(
                has_perfect_match  = False,
                total_candidates   = 0,
                intersection_count = 0,
                coverage           = coverage,
            )

        min_years = self._parse_min_years(jd_analysis.experience_years)

        # Step 1: Annotate every candidate
        annotated: list[TradeOffCandidate] = []
        for cs in all_scores:
            tc = self._annotate(cs, jd_analysis, min_years)
            annotated.append(tc)

        # Step 2: Sort -- fewest unmet first, then score desc
        annotated.sort(key=lambda c: (c.unmet_count, -c.total_score))

        # Separate perfect matches from compromise candidates
        perfect     = [c for c in annotated if c.unmet_count == 0]
        compromise  = [c for c in annotated if c.unmet_count > 0]

        # Assign ranks
        for i, tc in enumerate(perfect + compromise):
            tc.rank = i + 1

        has_perfect = len(perfect) > 0

        # Step 3: Groq narratives for top N compromise candidates (only if needed)
        top_compromise = compromise[:_GROQ_TOP_N]
        if top_compromise and self.gateway:
            try:
                self._add_groq_narratives(top_compromise, jd_analysis)
            except Exception as e:
                print(f"[TradeOffBuilder] Groq narrative failed, using Python fallback: {e}")
                for tc in top_compromise:
                    tc.tradeoff_note = self._python_narrative(tc, jd_analysis)
        else:
            # Python fallback narrative for all
            for tc in compromise:
                tc.tradeoff_note = self._python_narrative(tc, jd_analysis)

        # Perfect matches get a simple note
        for tc in perfect:
            tc.tradeoff_note = (
                f"{tc.candidate_name} satisfies all required criteria for "
                f"the {jd_analysis.role_title} position."
            )

        print(f"[TradeOffBuilder] Shortlist: {len(perfect)} perfect, "
              f"{len(compromise)} compromise candidates")

        return FeasibilityShortlist(
            has_perfect_match     = has_perfect,
            perfect_matches       = perfect,
            compromise_candidates = compromise,
            intersection_count    = len(perfect),
            total_candidates      = len(all_scores),
            coverage              = coverage,
        )

    # --- Candidate annotation ------------------------------------------

    def _annotate(
        self,
        cs:        CandidateScore,
        jd:        JDAnalysis,
        min_years: float,
    ) -> TradeOffCandidate:
        met, partial, unmet = [], [], []

        # Check each required skill
        for skill in jd.required_skills:
            status = self._skill_status(cs, skill)
            if status == "met":
                met.append(skill)
            elif status == "partial":
                partial.append(skill)
            else:
                unmet.append(skill)

        # Check experience
        if min_years > 0:
            candidate_yrs = cs.profile.total_experience_years if cs.profile else 0.0
            exp_label     = f"{jd.experience_years} experience"
            if candidate_yrs >= min_years:
                met.append(exp_label)
            elif candidate_yrs >= min_years * 0.7:
                partial.append(exp_label)
            else:
                unmet.append(exp_label)

        total_reqs    = len(met) + len(partial) + len(unmet)
        compromise    = unmet_count = len(unmet)
        comp_score    = compromise / max(total_reqs, 1)

        return TradeOffCandidate(
            candidate_id     = cs.candidate_id,
            candidate_name   = cs.candidate_name,
            total_score      = cs.total_score,
            met              = met,
            partial          = partial,
            unmet            = unmet,
            unmet_count      = unmet_count,
            compromise_score = round(comp_score, 3),
        )

    def _skill_status(self, cs: CandidateScore, skill: str) -> str:
        """Returns 'met', 'partial', or 'unmet' for a given skill."""
        for v in cs.skill_breakdown:
            if self._matches(v.jd_skill, skill):
                if v.status in _SKILL_STRONG:
                    return "met"
                if v.status in _SKILL_PASS:
                    return "partial"
                return "unmet"

        for m in cs.skill_matches:
            if self._matches(m.jd_skill, skill):
                if m.matched and m.similarity >= _MATCH_THRESH:
                    return "met"
                if m.matched:
                    return "partial"
                return "unmet"

        return "unmet"

    # --- Groq narratives -----------------------------------------------

    def _add_groq_narratives(
        self,
        candidates: list[TradeOffCandidate],
        jd:         JDAnalysis,
    ) -> None:
        decision = self.router.route(
            "generate candidate trade-off narrative",
            task_type_hint="tradeoff_narrative",
        )

        summaries = []
        for tc in candidates:
            met_str     = ", ".join(tc.met)     if tc.met     else "None"
            partial_str = ", ".join(tc.partial) if tc.partial else "None"
            unmet_str   = ", ".join(tc.unmet)   if tc.unmet   else "None"
            summaries.append(
                f"Candidate: {tc.candidate_name} (ID: {tc.candidate_id})\n"
                f"  Satisfies: {met_str}\n"
                f"  Partially meets: {partial_str}\n"
                f"  Does not meet: {unmet_str}"
            )

        prompt = TRADEOFF_PROMPT.format(
            role               = jd.role_title or "the role",
            candidate_summaries = "\n\n".join(summaries),
        )

        response = self.gateway.call(
            decision.model,
            [
                {"role": "system", "content": TRADEOFF_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            provider=decision.provider,
        )

        import json, re as _re
        try:
            cleaned = _re.sub(r"```(?:json)?", "", response.content).strip()
            notes   = json.loads(cleaned)
            note_map = {n["candidate_id"]: n["tradeoff_note"] for n in notes}
            for tc in candidates:
                if tc.candidate_id in note_map:
                    tc.tradeoff_note = note_map[tc.candidate_id]
                else:
                    tc.tradeoff_note = self._python_narrative(tc, jd)
        except Exception as e:
            print(f"[TradeOffBuilder] Parse error on Groq response: {e}")
            for tc in candidates:
                tc.tradeoff_note = self._python_narrative(tc, jd)

    # --- Python fallback narrative -------------------------------------

    @staticmethod
    def _python_narrative(tc: TradeOffCandidate, jd: JDAnalysis) -> str:
        parts = []
        if tc.met:
            parts.append(
                f"{tc.candidate_name} satisfies {len(tc.met)} of the required criteria "
                f"({', '.join(tc.met[:3])}{'...' if len(tc.met) > 3 else ''})."
            )
        if tc.partial:
            parts.append(
                f"The following requirements are only partially met: "
                f"{', '.join(tc.partial)}."
            )
        if tc.unmet:
            parts.append(
                f"The following requirements are not sufficiently supported by available evidence: "
                f"{', '.join(tc.unmet)}."
            )
        return " ".join(parts) or f"{tc.candidate_name} was evaluated against all requirements."

    # --- Helpers -------------------------------------------------------

    @staticmethod
    def _matches(jd_skill: str, target: str) -> bool:
        a = jd_skill.strip().lower()
        b = target.strip().lower()
        return a == b or b in a or a in b

    @staticmethod
    def _parse_min_years(exp_str: str) -> float:
        if not exp_str:
            return 0.0
        nums = re.findall(r"\d+\.?\d*", exp_str)
        return float(nums[0]) if nums else 0.0
