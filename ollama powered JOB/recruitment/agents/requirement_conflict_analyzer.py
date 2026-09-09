"""
RecruitScreen -- Requirement Conflict Analyzer
----------------------------------------------
Detects internal conflicts *within* the JD requirements before any candidates
are evaluated. Runs immediately after Stage 2 (JD Analysis).

Examples of conflicts detected:
  HIGH     -- "5+ years experience" + "Junior-level position"
  HIGH     -- "10+ years" + "Junior" + "Salary <= 8 LPA"
  MODERATE -- "Senior role" + market-below salary
  MODERATE -- "Entry-level" + required certifications (e.g. CKA, AWS SA Pro)
  NONE     -- Normal, consistent requirements

Model routing:
  Routine / clear-cut checks -> Llama 3.2 (local)
  Ambiguous / borderline     -> Groq (cloud), same escalation pattern as EvidenceVerifier
"""

import json
import re
from ..models import (
    JDAnalysis, FeasibilityReport, RequirementConflict, ConflictSeverity,
)


# --- Prompts -----------------------------------------------------------

SYSTEM_PROMPT = """You are a recruitment requirements auditor. Your task is to detect
whether a job description's requirements create internal conflicts that would make it
difficult or impossible to find a qualifying candidate.

Be objective and factual. Output valid JSON only."""


CONFLICT_PROMPT = """Analyze these job requirements for internal conflicts.

Role: {role_title}
Seniority Level: {seniority_level}
Required Skills: {required_skills}
Experience Required: {experience_years}
Salary Range: {salary_info}
Certifications: {certifications}
Education: {education}

A conflict exists when requirements that are individually reasonable become
contradictory or highly restrictive when combined.

Common conflict patterns:
- High experience years (5+) combined with Junior seniority level -> HIGH conflict
- Senior-level role with salary below typical market floor for that level -> MODERATE
- Entry-level position requiring advanced certifications (e.g. AWS SA Pro, CKA) -> MODERATE
- Multiple simultaneous constraints that together describe a very rare profile -> MODERATE
- Requirements that directly contradict each other -> HIGH

Return a JSON object:
{{
  "conflicts": [
    {{
      "requirement_a": "the first conflicting requirement (be specific)",
      "requirement_b": "the conflicting second requirement or combination",
      "severity": "HIGH | MODERATE | NONE",
      "explanation": "Factual, specific reason why this combination is problematic."
    }}
  ],
  "overall_severity": "HIGH | MODERATE | NONE",
  "recruiter_advisory": "2-3 sentence plain-English advisory for the recruiter. Focus on what makes the pool small or the requirements contradictory. Never use accusatory language."
}}

If no conflicts exist, return:
{{"conflicts": [], "overall_severity": "NONE", "recruiter_advisory": "The requirements appear consistent."}}

Output ONLY valid JSON, nothing else."""


# --- Ambiguity detection -----------------------------------------------

_AMBIGUITY_SIGNALS = (
    "unclear", "ambiguous", "uncertain", "depends on", "context-dependent",
    "may or may not", "could be", "not sure", "borderline",
)

_JUNIOR_MAX_YEARS = 3
_SENIOR_MIN_YEARS = 5


class RequirementConflictAnalyzer:
    """
    Detects self-conflicts within JD requirements.
    Routes to Llama 3.2 first; escalates to Groq only for ambiguous cases.
    """

    def __init__(self, gateway=None, router=None):
        self.gateway = gateway
        self.router  = router

    def analyze(self, jd_analysis: JDAnalysis) -> FeasibilityReport:
        """
        Analyze a JDAnalysis for internal requirement conflicts.
        Returns a FeasibilityReport regardless of whether a gateway is available.
        """
        heuristic_report = self._heuristic_check(jd_analysis)

        if not self.gateway:
            return heuristic_report

        try:
            llm_report = self._call_llm(jd_analysis, provider="ollama")

            if llm_report and self._severity_rank(llm_report.overall_severity) > \
                              self._severity_rank(heuristic_report.overall_severity):
                merged = llm_report
                existing = {(c.requirement_a, c.requirement_b) for c in merged.conflicts}
                for hc in heuristic_report.conflicts:
                    if (hc.requirement_a, hc.requirement_b) not in existing:
                        merged.conflicts.append(hc)
                return merged

            if llm_report and self._is_ambiguous(llm_report):
                print("[ConflictAnalyzer] Ambiguous result from Llama, escalating to Groq")
                groq_report = self._call_llm(jd_analysis, provider="groq")
                if groq_report:
                    return groq_report

            return llm_report or heuristic_report

        except Exception as e:
            print(f"[ConflictAnalyzer] LLM call failed, using heuristics: {e}")
            return heuristic_report

    def _call_llm(self, jd: JDAnalysis, provider: str):
        task_hint = (
            "requirement_conflict_detection" if provider == "ollama"
            else "requirement_conflict_ambiguous"
        )
        decision = self.router.route(
            "detect requirement conflicts in job description",
            task_type_hint=task_hint,
        )

        salary_info = getattr(jd, "salary_range", "") or "Not specified"
        prompt = CONFLICT_PROMPT.format(
            role_title       = jd.role_title or "Not specified",
            seniority_level  = jd.seniority_level or "Not specified",
            required_skills  = ", ".join(jd.required_skills) or "Not specified",
            experience_years = jd.experience_years or "Not specified",
            salary_info      = salary_info,
            certifications   = ", ".join(jd.certifications) or "None",
            education        = ", ".join(jd.education) or "Not specified",
        )

        response = self.gateway.call(
            decision.model,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            provider=provider,
        )
        return self._parse_response(response.content)

    def _heuristic_check(self, jd: JDAnalysis) -> FeasibilityReport:
        """Fast rule-based conflict detection that runs even without an LLM."""
        conflicts = []
        exp_years = self._parse_experience_years(jd.experience_years)
        seniority = (jd.seniority_level or "").lower()

        # Rule 1: High experience + Junior title
        if exp_years is not None and exp_years >= _JUNIOR_MAX_YEARS and "junior" in seniority:
            conflicts.append(RequirementConflict(
                requirement_a = f"{exp_years}+ years experience required",
                requirement_b = f"Seniority level: {jd.seniority_level}",
                severity      = ConflictSeverity.HIGH,
                explanation   = (
                    f"Requiring {exp_years}+ years of experience for a Junior-level "
                    f"position significantly contradicts standard industry definitions. "
                    f"This combination describes a very small or non-existent candidate pool."
                ),
            ))

        # Rule 2: Low experience + Senior title
        if exp_years is not None and exp_years < _SENIOR_MIN_YEARS and "senior" in seniority:
            conflicts.append(RequirementConflict(
                requirement_a = f"{exp_years} years experience required",
                requirement_b = f"Seniority level: {jd.seniority_level}",
                severity      = ConflictSeverity.MODERATE,
                explanation   = (
                    f"Requiring only {exp_years} years experience for a Senior role "
                    f"is unusual. Most industry norms expect 5+ years for Senior positions."
                ),
            ))

        # Rule 3: Entry-level + advanced certs
        _ADVANCED_CERTS = {
            "cka", "ckad", "aws sa professional",
            "aws solutions architect professional",
            "gcp professional", "cissp", "cism", "pmp",
        }
        is_entry = "junior" in seniority or "entry" in seniority or (
            exp_years is not None and exp_years <= 1
        )
        if is_entry:
            for cert in jd.certifications:
                if any(ac in cert.lower() for ac in _ADVANCED_CERTS):
                    conflicts.append(RequirementConflict(
                        requirement_a = "Entry-level / junior position",
                        requirement_b = f"Required certification: {cert}",
                        severity      = ConflictSeverity.MODERATE,
                        explanation   = (
                            f"The certification '{cert}' typically requires several years of "
                            f"hands-on experience and is rarely held by entry-level candidates."
                        ),
                    ))

        if not conflicts:
            return FeasibilityReport(
                conflicts          = [],
                overall_severity   = ConflictSeverity.NONE,
                recruiter_advisory = "No obvious conflicts detected in the requirements.",
            )

        severities = [c.severity for c in conflicts]
        overall = ConflictSeverity.HIGH if ConflictSeverity.HIGH in severities else ConflictSeverity.MODERATE

        return FeasibilityReport(
            conflicts          = conflicts,
            overall_severity   = overall,
            recruiter_advisory = self._build_heuristic_advisory(conflicts, jd),
        )

    def _parse_response(self, raw: str):
        try:
            cleaned = re.sub(r"```(?:json)?", "", raw).strip()
            data    = json.loads(cleaned)

            conflicts = []
            for c in data.get("conflicts", []):
                try:
                    severity = ConflictSeverity(c.get("severity", "NONE").upper())
                except ValueError:
                    severity = ConflictSeverity.NONE
                conflicts.append(RequirementConflict(
                    requirement_a = str(c.get("requirement_a", "")),
                    requirement_b = str(c.get("requirement_b", "")),
                    severity      = severity,
                    explanation   = str(c.get("explanation", "")),
                ))

            try:
                overall = ConflictSeverity(data.get("overall_severity", "NONE").upper())
            except ValueError:
                overall = ConflictSeverity.NONE

            return FeasibilityReport(
                conflicts          = conflicts,
                overall_severity   = overall,
                recruiter_advisory = str(data.get("recruiter_advisory", "")),
            )
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[ConflictAnalyzer] Parse error: {e}")
            return None

    @staticmethod
    def _parse_experience_years(exp_str: str):
        if not exp_str:
            return None
        nums = re.findall(r"\d+\.?\d*", exp_str)
        return float(nums[0]) if nums else None

    @staticmethod
    def _severity_rank(s: ConflictSeverity) -> int:
        return {"NONE": 0, "MODERATE": 1, "HIGH": 2}.get(s.value, 0)

    @staticmethod
    def _is_ambiguous(report: FeasibilityReport) -> bool:
        advisory_lower = report.recruiter_advisory.lower()
        return any(sig in advisory_lower for sig in _AMBIGUITY_SIGNALS)

    @staticmethod
    def _build_heuristic_advisory(conflicts, jd: JDAnalysis) -> str:
        parts = [
            f"The job requisition for '{jd.role_title}' contains "
            f"{len(conflicts)} detected requirement conflict(s)."
        ]
        for c in conflicts:
            parts.append(f"* {c.explanation}")
        parts.append(
            "These constraints may significantly reduce the available candidate pool. "
            "Consider revising the requirements to better reflect the actual position needs."
        )
        return " ".join(parts)
