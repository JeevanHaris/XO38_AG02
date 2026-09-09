"""
RecruitScreen v1.0 — JD Analyzer Agent
────────────────────────────────────────
Extracts structured requirements from a raw job description text.

Output schema:
  {
    "role_title":       str,
    "seniority_level":  str,
    "required_skills":  list[str],
    "preferred_skills": list[str],
    "experience_years": str,
    "education":        list[str],
    "certifications":   list[str],
    "responsibilities": list[str],
  }
"""

import json
import re
from ..models import JDAnalysis


SYSTEM_PROMPT = """You are an expert recruitment analyst. Your task is to extract structured information from job descriptions.

Extract ONLY what is explicitly stated. Do NOT invent or infer skills not mentioned.
Be precise and factual. Output valid JSON only — no markdown, no explanation."""


EXTRACTION_PROMPT = """Analyze this job description and extract structured requirements.

Job Description:
\"\"\"
{jd_text}
\"\"\"

Return a JSON object with EXACTLY these fields:
{{
  "role_title":       "string — the job title",
  "seniority_level":  "string — Junior/Mid/Senior/Lead/Principal or as stated",
  "required_skills":  ["list of must-have technical skills, max 15 items"],
  "preferred_skills": ["list of nice-to-have skills, max 10 items"],
  "experience_years": "string — e.g. '3-5 years', '2+ years', or 'Not specified'",
  "education":        ["list of education requirements, e.g. 'Bachelor in CS'"],
  "certifications":   ["list of required/preferred certifications"],
  "responsibilities": ["list of key job responsibilities, max 8 items"]
}}

Rules:
- required_skills: Only skills explicitly marked as required/must-have
- preferred_skills: Skills marked as preferred/nice-to-have/bonus
- Keep skill names concise: "Python", "REST APIs", "PostgreSQL", "Docker"
- If a section is not mentioned, return empty list []
- Output ONLY valid JSON, nothing else"""


class JDAnalyzerAgent:
    """Extracts structured requirements from job description text using an LLM."""

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

    def analyze(self, jd_text: str, filename: str = "") -> JDAnalysis:
        """
        Analyze a job description and return a structured JDAnalysis.

        Args:
            jd_text:  Raw text of the job description
            filename: Original filename (for reference)

        Returns:
            JDAnalysis dataclass
        """
        if not jd_text or not jd_text.strip():
            return JDAnalysis(filename=filename)

        # Truncate very long JDs to stay within context window
        text = jd_text[:8000] if len(jd_text) > 8000 else jd_text

        # Route to local model (extraction task)
        decision = self.router.route("extract job description requirements",
                                     task_type_hint="extraction")

        prompt = EXTRACTION_PROMPT.format(jd_text=text)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]

        try:
            response = self.gateway.call(
                decision.model, messages, provider=decision.provider
            )
            raw = response.content.strip()
            data = self._parse_json(raw)

            print(f"[JDAnalyzer] Extracted: {len(data.get('required_skills', []))} "
                  f"required, {len(data.get('preferred_skills', []))} preferred skills")

            return JDAnalysis(
                role_title        = data.get("role_title", ""),
                seniority_level   = data.get("seniority_level", ""),
                required_skills   = self._clean_list(data.get("required_skills", [])),
                preferred_skills  = self._clean_list(data.get("preferred_skills", [])),
                experience_years  = data.get("experience_years", "Not specified"),
                education         = self._clean_list(data.get("education", [])),
                certifications    = self._clean_list(data.get("certifications", [])),
                responsibilities  = self._clean_list(data.get("responsibilities", [])),
                raw_text          = jd_text,
                filename          = filename,
            )

        except Exception as e:
            print(f"[JDAnalyzer] Error: {e}")
            # Return minimal fallback
            return JDAnalysis(raw_text=jd_text, filename=filename)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Extract and parse JSON from LLM output (handles markdown fences)."""
        # Strip markdown code fences
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"```\s*$", "", raw).strip()

        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object within the text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        print(f"[JDAnalyzer] Failed to parse JSON from: {raw[:200]}")
        return {}

    @staticmethod
    def _clean_list(items: list) -> list[str]:
        """Normalize a list of strings — deduplicate, strip, remove empties."""
        if not isinstance(items, list):
            return []
        seen   = set()
        result = []
        for item in items:
            s = str(item).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                result.append(s)
        return result
