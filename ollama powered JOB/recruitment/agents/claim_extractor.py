"""
RecruitScreen v1.0 — Claim Extractor Agent
────────────────────────────────────────────
Maps JD required skills to the specific resume claims that are relevant to them.
Focuses only on JD-relevant skills (targeted, not exhaustive).

For each required_skill in the JD, finds the specific statement in the resume
that most directly relates to that skill. Does NOT judge truthfulness.
"""

import json
import re
from ..models import Claim, JDAnalysis, CandidateProfile


SYSTEM_PROMPT = """You are an expert technical recruiter. Your job is to identify
specific claims in a resume that relate to job requirements. 
Be precise and factual. Output valid JSON only."""


EXTRACTION_PROMPT = """Given a job's required skills and a candidate's resume, 
extract the most relevant claim from the resume for each required skill.

Required Skills: {skills_list}

Resume Text:
\"\"\"
{resume_text}
\"\"\"

For EACH required skill, find the most specific statement in the resume that relates to it.
If the resume has no relevant statement for a skill, use an empty string.

Return a JSON array:
[
  {{
    "jd_skill":       "the required skill from the job description",
    "skill":          "the skill as mentioned in the resume (may differ slightly)",
    "statement":      "the specific resume statement supporting this skill, or '' if none",
    "source_section": "which section of the resume (e.g. Skills, Work Experience, Projects)"
  }}
]

Rules:
- One entry per required skill
- statement should be a direct quote or close paraphrase from the resume
- If skill not mentioned at all, set statement to "" and source_section to "Not Found"
- Output ONLY valid JSON array, nothing else"""


class ClaimExtractorAgent:
    """
    Maps JD required skills to the relevant resume claims.
    Creates one Claim per required skill, with the most relevant resume statement.
    """

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

    def extract(
        self,
        jd_analysis:  JDAnalysis,
        profile:      CandidateProfile,
    ) -> list[Claim]:
        """
        Extract claims for each required JD skill from the candidate's resume.

        Args:
            jd_analysis:  Structured JD analysis (required_skills used)
            profile:      Candidate's parsed profile

        Returns:
            list[Claim] — one per required skill
        """
        if not jd_analysis.required_skills or not profile.raw_text:
            return []

        skills_list = "\n".join(
            f"- {s}" for s in jd_analysis.required_skills
        )

        # Truncate resume for context window
        resume_text = profile.raw_text[:8000] if len(profile.raw_text) > 8000 else profile.raw_text

        decision = self.router.route(
            "extract claims from resume for job skills",
            task_type_hint="extraction",
        )

        prompt = EXTRACTION_PROMPT.format(
            skills_list=skills_list,
            resume_text=resume_text,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]

        try:
            response = self.gateway.call(
                decision.model, messages, provider=decision.provider
            )
            raw   = response.content.strip()
            items = self._parse_json_array(raw)

            claims = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                claim = Claim(
                    skill           = str(item.get("skill", item.get("jd_skill", ""))).strip(),
                    statement       = str(item.get("statement", "")).strip(),
                    source_section  = str(item.get("source_section", "")).strip(),
                    jd_skill        = str(item.get("jd_skill", "")).strip(),
                    candidate_id    = profile.candidate_id,
                )
                claims.append(claim)

            print(f"[ClaimExtractor] {profile.name}: {len(claims)} claims extracted "
                  f"for {len(jd_analysis.required_skills)} required skills")
            return claims

        except Exception as e:
            print(f"[ClaimExtractor] Error for {profile.name}: {e}")
            # Fallback: create empty claims for each required skill
            return [
                Claim(
                    skill        = skill,
                    jd_skill     = skill,
                    statement    = "",
                    source_section = "Error",
                    candidate_id = profile.candidate_id,
                )
                for skill in jd_analysis.required_skills
            ]

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_array(raw: str) -> list:
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"```\s*$", "", raw).strip()
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                # Sometimes LLM wraps in {"claims": [...]}
                for v in result.values():
                    if isinstance(v, list):
                        return v
        except json.JSONDecodeError:
            pass
        # Try to find array in text
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
        print(f"[ClaimExtractor] Failed to parse JSON array: {raw[:200]}")
        return []
