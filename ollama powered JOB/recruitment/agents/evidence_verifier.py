"""
RecruitScreen v1.0 — Evidence Verifier Agent
─────────────────────────────────────────────
Uses Qwen3 (local) or Groq (cloud) to judge whether retrieved evidence
actually supports a skill claim.

Verdict categories:
  STRONGLY_SUPPORTED  🟢 — Clear, direct evidence
  PARTIALLY_SUPPORTED 🟡 — Related but indirect / implied
  UNSUPPORTED         🔴 — Claim made but no evidence found
  NOT_MENTIONED       ⚪ — Skill not referenced anywhere
"""

import json
import re
from ..models import (
    Claim, Evidence, VerificationResult, VerificationStatus
)


SYSTEM_PROMPT = """You are an expert technical recruiter reviewing evidence for candidate skill claims.
Your job is to determine if the provided resume evidence supports a specific skill claim.
Be objective, precise, and consistent. Output valid JSON only."""


VERIFICATION_PROMPT = """Evaluate whether the resume evidence supports the claimed skill.

Skill Being Verified: {skill}

Candidate Statement (from claim extraction):
"{statement}"

Evidence Found in Resume:
{evidence_text}

Classify the evidence strength using EXACTLY one of these verdicts:
- STRONGLY_SUPPORTED: Clear, direct evidence of this skill (e.g., "Built 3 FastAPI projects", specific tech mentioned with context)
- PARTIALLY_SUPPORTED: Related but indirect evidence (e.g., mentions adjacent technology, general mention without project depth)
- UNSUPPORTED: Skill was claimed but the evidence does NOT support it
- NOT_MENTIONED: No evidence of this skill found in the resume at all

Return a JSON object:
{{
  "verdict":    "STRONGLY_SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | NOT_MENTIONED",
  "confidence": 0.0-1.0,
  "explanation": "1-2 sentence explanation of your decision"
}}

Output ONLY valid JSON, nothing else."""


class EvidenceVerifierAgent:
    """
    Uses an LLM to judge whether retrieved evidence supports a claim.

    Routing:
      - Simple/clear cases → local Qwen3:4b
      - Complex/ambiguous → Groq (better reasoning)
    """

    AMBIGUITY_SIGNALS = [
        "related", "similar", "adjacent", "framework", "experience with",
        "familiarity", "exposure", "worked alongside",
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

        Args:
            claim:    The claim to verify
            evidence: Retrieved evidence passages (may be empty)

        Returns:
            VerificationResult
        """
        # No evidence at all → NOT_MENTIONED
        if not evidence:
            return VerificationResult(
                claim         = claim,
                evidence      = [],
                status        = VerificationStatus.NOT_MENTIONED,
                explanation   = f"No evidence of '{claim.jd_skill}' found in the resume.",
                confidence_score = 1.0,
                jd_skill      = claim.jd_skill,
            )

        # Format evidence for LLM
        evidence_text = self._format_evidence(evidence)

        # Determine complexity → choose provider
        is_complex = self._is_complex_case(claim, evidence)
        task_type  = "complex_reasoning" if is_complex else "verification_simple"
        decision   = self.router.route(claim.jd_skill, task_type_hint=task_type)

        prompt = VERIFICATION_PROMPT.format(
            skill         = claim.jd_skill,
            statement     = claim.statement or "No specific statement found",
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
                confidence = float(data.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.5

            result = VerificationResult(
                claim            = claim,
                evidence         = evidence,
                status           = status,
                explanation      = str(data.get("explanation", "")).strip(),
                confidence_score = confidence,
                jd_skill         = claim.jd_skill,
            )

            print(f"[EvidenceVerifier] '{claim.jd_skill}' → {status.value} "
                  f"(conf={confidence:.2f}, via {decision.provider})")
            return result

        except Exception as e:
            print(f"[EvidenceVerifier] Error for '{claim.jd_skill}': {e}")
            return VerificationResult(
                claim            = claim,
                evidence         = evidence,
                status           = VerificationStatus.PARTIALLY_SUPPORTED,
                explanation      = f"Verification error: {e}",
                confidence_score = 0.3,
                jd_skill         = claim.jd_skill,
            )

    def verify_all(
        self,
        claims:          list[Claim],
        evidence_map:    dict[str, list[Evidence]],
    ) -> list[VerificationResult]:
        """
        Verify all claims using their corresponding evidence.

        Args:
            claims:       List of claims to verify
            evidence_map: Dict mapping jd_skill → list[Evidence]

        Returns:
            list[VerificationResult] in same order as claims
        """
        results = []
        for claim in claims:
            key      = claim.jd_skill or claim.skill
            evidence = evidence_map.get(key, [])
            result   = self.verify(claim, evidence)
            results.append(result)
        return results

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _format_evidence(evidence: list[Evidence]) -> str:
        if not evidence:
            return "No evidence found."
        parts = []
        for i, e in enumerate(evidence[:3], 1):
            score = f"(relevance: {e.similarity_score:.2f})"
            parts.append(f"[Passage {i} — {e.source_section} {score}]\n{e.chunk_text}")
        return "\n\n".join(parts)

    def _is_complex_case(self, claim: Claim, evidence: list[Evidence]) -> bool:
        """Detect ambiguous cases that benefit from Groq's reasoning."""
        if not evidence:
            return False
        # If all evidence has medium-range similarity (not clearly related or unrelated)
        scores = [e.similarity_score for e in evidence]
        avg_score = sum(scores) / len(scores) if scores else 0
        if 0.25 < avg_score < 0.55:
            return True
        # If claim statement mentions ambiguous terms
        stmt_lower = (claim.statement or "").lower()
        if any(sig in stmt_lower for sig in self.AMBIGUITY_SIGNALS):
            return True
        return False

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"```\s*$", "", raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return {}
