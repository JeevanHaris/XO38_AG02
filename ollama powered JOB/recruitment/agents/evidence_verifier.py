"""
RecruitScreen / ARIA Core — Evidence Verifier Agent
──────────────────────────────────────────────────
Evaluates: "What evidence in the candidate's application supports the claim?"

Classification:
  🟢 STRONGLY_SUPPORTED  — Certification + Project / Work Experience evidence
  🟡 PARTIALLY_SUPPORTED — Mentioned only in Skills section, no project or work evidence
  🔴 UNSUPPORTED         — Claimed but contradicted, or completely unevidenced
  ⚪ NOT_MENTIONED       — Skill not referenced anywhere in application
"""

import json
import re
from ..models import (
    Claim, Evidence, VerificationResult, VerificationStatus
)


SYSTEM_PROMPT = """You are an evidence-based technical talent screening agent.
Your primary question is NOT "Does the candidate know X?", but:
"What concrete evidence in the candidate's application supports this skill claim?"
Be objective, rigorous, and explainable. Output valid JSON only."""


VERIFICATION_PROMPT = """Evaluate what evidence in the candidate's application supports the skill claim.

Requirement: {skill}
Candidate Claim: "{statement}"

Evidence Extracted from Application:
\"\"\"
{evidence_text}
\"\"\"

Classify using EXACTLY one of these verdicts:
- STRONGLY_SUPPORTED: Clear, direct evidence (e.g., certification, production project, or demonstrable work experience using the skill).
- PARTIALLY_SUPPORTED: Mentioned only in the Skills list, or general mention without demonstrable project or experience evidence.
- UNSUPPORTED: The skill was claimed but the evidence contradicts it or shows no actual usage.
- NOT_MENTIONED: The skill is completely absent from the candidate's application.

Return a JSON object:
{{
  "verdict": "STRONGLY_SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | NOT_MENTIONED",
  "confidence": 0.0-1.0,
  "explanation": "Concise factual reason citing what evidence exists (or is missing)."
}}

Output ONLY valid JSON, nothing else."""


class EvidenceVerifierAgent:
    """
    Judges whether retrieved evidence supports a skill claim.
    Routes routine checks to local Llama 3.2 and ambiguous/difficult cases to Groq.
    """

    AMBIGUITY_SIGNALS = [
        "related", "similar", "adjacent", "familiarity", "exposure",
        "borderline", "hybrid", "transferred", "implied",
    ]

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

    def verify(
        self,
        claim:    Claim,
        evidence: list[Evidence],
    ) -> VerificationResult:
        """
        Verify whether evidence supports a claim.
        """
        if not evidence:
            return VerificationResult(
                claim            = claim,
                evidence         = [],
                status           = VerificationStatus.NOT_MENTIONED,
                explanation      = f"No evidence of '{claim.jd_skill}' found in the candidate application.",
                confidence_score = 1.0,
                jd_skill         = claim.jd_skill,
            )

        # Quick heuristic if only mentioned in Skills section without any other evidence
        if len(evidence) == 1 and evidence[0].source_section == "Skills":
            return VerificationResult(
                claim            = claim,
                evidence         = evidence,
                status           = VerificationStatus.PARTIALLY_SUPPORTED,
                explanation      = f"'{claim.jd_skill}' is mentioned only in the Skills section without project or experience evidence.",
                confidence_score = 0.90,
                jd_skill         = claim.jd_skill,
            )

        evidence_text = self._format_evidence(evidence)
        is_complex    = self._is_complex_case(claim, evidence)
        task_type     = "difficult_evidence_verification" if is_complex else "basic_evidence_check"
        decision      = self.router.route(claim.jd_skill, task_type_hint=task_type)

        prompt = VERIFICATION_PROMPT.format(
            skill         = claim.jd_skill,
            statement     = claim.statement or f"Candidate possesses {claim.jd_skill}",
            evidence_text = evidence_text,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]

        try:
            response = self.gateway.call(
                decision.model, messages, provider=decision.provider
            )
            raw  = response.content.strip()
            data = self._parse_json(raw)

            verdict_str = data.get("verdict", "NOT_MENTIONED").upper().strip()
            try:
                status = VerificationStatus(verdict_str)
            except ValueError:
                status = VerificationStatus.NOT_MENTIONED

            try:
                confidence = float(data.get("confidence", 0.85))
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.85

            return VerificationResult(
                claim            = claim,
                evidence         = evidence,
                status           = status,
                explanation      = str(data.get("explanation", "")).strip(),
                confidence_score = confidence,
                jd_skill         = claim.jd_skill,
            )

        except Exception as e:
            print(f"[EvidenceVerifier] Fallback verification for {claim.jd_skill}: {e}")
            # Fallback heuristic
            has_project = any(e.source_section in ("Projects", "Certifications", "Work Experience") for e in evidence)
            status = VerificationStatus.STRONGLY_SUPPORTED if has_project else VerificationStatus.PARTIALLY_SUPPORTED
            return VerificationResult(
                claim            = claim,
                evidence         = evidence,
                status           = status,
                explanation      = f"Evidence found across {', '.join(set(e.source_section for e in evidence))}.",
                confidence_score = 0.75,
                jd_skill         = claim.jd_skill,
            )

    def verify_all(
        self,
        claims:       list[Claim],
        evidence_map: dict[str, list[Evidence]],
    ) -> list[VerificationResult]:
        results = []
        for claim in claims:
            ev_list = evidence_map.get(claim.jd_skill, [])
            res = self.verify(claim, ev_list)
            results.append(res)
        return results

    def _is_complex_case(self, claim: Claim, evidence: list[Evidence]) -> bool:
        stmt = (claim.statement or "").lower()
        if any(w in stmt for w in self.AMBIGUITY_SIGNALS):
            return True
        return False

    @staticmethod
    def _format_evidence(evidence: list[Evidence]) -> str:
        if not evidence:
            return "No specific evidence passages found."
        lines = []
        for i, ev in enumerate(evidence, 1):
            sec = f"[{ev.source_section}] " if ev.source_section else ""
            lines.append(f"{i}. {sec}{ev.chunk_text.strip()}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"```\s*$", "", raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}
