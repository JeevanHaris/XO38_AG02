"""
RecruitScreen v1.0 — Resume Analyzer Agent
───────────────────────────────────────────
Extracts structured profile information from resume text.
Does NOT verify claims — that is the Evidence Verifier's job.

Output: CandidateProfile dataclass
"""

import json
import re
from ..models import CandidateProfile, ExperienceEntry


SYSTEM_PROMPT = """You are an expert resume parser. Extract structured information from resumes.
Extract ONLY what is explicitly stated. Do NOT fabricate or assume anything.
Output valid JSON only — no markdown, no explanation."""


EXTRACTION_PROMPT = """Parse this resume and extract structured information.

Resume:
\"\"\"
{resume_text}
\"\"\"

Return a JSON object with EXACTLY these fields:
{{
  "name":  "Full name of the candidate",
  "email": "Email address or empty string",
  "phone": "Phone number or empty string",
  "skills": ["list of all technical skills mentioned"],
  "experience_entries": [
    {{
      "title":       "Job title",
      "company":     "Company name",
      "duration":    "e.g. Jan 2022 - Dec 2023 or 2 years",
      "description": "Brief description of role/achievements (1-2 sentences)"
    }}
  ],
  "total_experience_years": 0.0,
  "projects": ["brief description of notable projects, max 5"],
  "education": ["e.g. 'B.Tech Computer Science, IIT Delhi, 2020'"],
  "certifications": ["list of certifications"],
  "raw_claims": [
    "List of specific achievement claims the candidate makes",
    "e.g. 'Reduced API latency by 40%'",
    "e.g. 'Built ML model with 95% accuracy'",
    "e.g. 'Led team of 5 engineers'"
  ]
}}

Rules:
- skills: Include ALL technical skills (languages, frameworks, tools, platforms)
- raw_claims: Only specific, measurable claims — not generic statements
- total_experience_years: Calculate from experience_entries durations, use 0.0 if unclear
- Output ONLY valid JSON, nothing else"""


class ResumeAnalyzerAgent:
    """Extracts structured profile from resume text using an LLM."""

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

    def analyze(
        self,
        resume_text: str,
        candidate_name: str = "",
        candidate_id:   str = "",
        filename:       str = "",
    ) -> CandidateProfile:
        """
        Analyze a resume and return a CandidateProfile.

        Args:
            resume_text:    Raw text of the resume
            candidate_name: Pre-inferred name (from DocumentProcessor)
            candidate_id:   UUID for this candidate
            filename:       Original filename

        Returns:
            CandidateProfile dataclass
        """
        if not resume_text or not resume_text.strip():
            return CandidateProfile(
                candidate_id=candidate_id,
                name=candidate_name,
                filename=filename,
            )

        # Truncate very long resumes
        text = resume_text[:10000] if len(resume_text) > 10000 else resume_text

        decision = self.router.route(
            "extract resume skills and experience",
            task_type_hint="extraction",
        )

        prompt = EXTRACTION_PROMPT.format(resume_text=text)
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

            # Build experience entries
            exp_entries = []
            for e in data.get("experience_entries", []):
                exp_entries.append(ExperienceEntry(
                    title       = str(e.get("title", "")).strip(),
                    company     = str(e.get("company", "")).strip(),
                    duration    = str(e.get("duration", "")).strip(),
                    description = str(e.get("description", "")).strip(),
                ))

            # Use pre-inferred name if LLM returns empty
            name = str(data.get("name", "")).strip() or candidate_name

            # Clamp experience years
            try:
                exp_years = float(data.get("total_experience_years", 0.0))
                exp_years = max(0.0, min(exp_years, 50.0))
            except (ValueError, TypeError):
                exp_years = 0.0

            profile = CandidateProfile(
                candidate_id           = candidate_id,
                name                   = name,
                email                  = str(data.get("email", "")).strip(),
                phone                  = str(data.get("phone", "")).strip(),
                skills                 = self._clean_list(data.get("skills", [])),
                experience_entries     = exp_entries,
                total_experience_years = exp_years,
                projects               = self._clean_list(data.get("projects", [])),
                education              = self._clean_list(data.get("education", [])),
                certifications         = self._clean_list(data.get("certifications", [])),
                raw_claims             = self._clean_list(data.get("raw_claims", [])),
                raw_text               = resume_text,
                filename               = filename,
            )

            print(f"[ResumeAnalyzer] {name}: {len(profile.skills)} skills, "
                  f"{len(exp_entries)} jobs, {len(profile.raw_claims)} claims")
            return profile

        except Exception as e:
            print(f"[ResumeAnalyzer] Error for {candidate_name}: {e}")
            return CandidateProfile(
                candidate_id=candidate_id,
                name=candidate_name,
                raw_text=resume_text,
                filename=filename,
            )

    # ── Helpers ───────────────────────────────────────────────────────

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
        print(f"[ResumeAnalyzer] Failed to parse JSON: {raw[:200]}")
        return {}

    @staticmethod
    def _clean_list(items) -> list[str]:
        if not isinstance(items, list):
            return []
        seen, result = set(), []
        for item in items:
            s = str(item).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                result.append(s)
        return result
