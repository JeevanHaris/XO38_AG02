"""
RecruitScreen / ARIA Core — JD Analyzer Agent
────────────────────────────────────────────
Sends the Job Description to Llama 3.2 and validates structured output using Pydantic.

Schema:
{
  "role_title": "Web Developer",
  "seniority_level": "Junior",
  "required_skills": ["HTML", "CSS", "JavaScript", "REST APIs"],
  "preferred_skills": ["React", "Python", "PostgreSQL"],
  "experience": "0-2 years",
  "education": "Computer Science or related",
  "certifications": [],
  "responsibilities": []
}
"""

import json
import re
from typing import List, Union
from pydantic import BaseModel, Field, field_validator
from ..models import JDAnalysis


class JDAnalysisSchema(BaseModel):
    """Pydantic schema to validate and normalize Llama 3.2 output for Job Descriptions."""
    role_title: str = Field(default="Software Engineer")
    seniority_level: str = Field(default="Not specified")
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience: str = Field(default="Not specified")
    education: Union[List[str], str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)

    @field_validator("required_skills", "preferred_skills", "certifications", "responsibilities", mode="before")
    @classmethod
    def clean_string_list(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            seen = set()
            cleaned = []
            for item in v:
                s = str(item).strip()
                if s and s.lower() not in seen:
                    seen.add(s.lower())
                    cleaned.append(s)
            return cleaned
        return []

    @field_validator("education", mode="before")
    @classmethod
    def clean_education(cls, v):
        if isinstance(v, str):
            return [v.strip()] if v.strip() else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []


SYSTEM_PROMPT = """You are an expert recruitment analyst. Your task is to extract structured requirements from job descriptions.
Extract ONLY what is explicitly stated. Do NOT invent or infer skills not mentioned.
Be precise and factual. Output valid JSON only — no markdown, no explanation."""


EXTRACTION_PROMPT = """Analyze this job description and extract structured requirements.

Job Description:
\"\"\"
{jd_text}
\"\"\"

Return a JSON object with EXACTLY these fields:
{{
  "role_title": "string — the job title",
  "seniority_level": "string — Junior/Mid/Senior/Lead or as stated",
  "required_skills": ["HTML", "CSS", "JavaScript", "REST APIs"],
  "preferred_skills": ["React", "Python", "PostgreSQL"],
  "experience": "0-2 years",
  "education": "Computer Science or related",
  "certifications": ["list of required/preferred certifications"],
  "responsibilities": ["list of key responsibilities, max 6"]
}}

Rules:
- required_skills: Only skills explicitly required/must-have
- preferred_skills: Skills marked as preferred/nice-to-have
- Keep skill names concise: "HTML", "CSS", "JavaScript", "REST APIs", "Python"
- Output ONLY valid JSON, nothing else"""


class JDAnalyzerAgent:
    """Extracts structured requirements from JD text using Llama 3.2 and validates with Pydantic."""

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

    def analyze(self, jd_text: str, filename: str = "") -> JDAnalysis:
        if not jd_text or not jd_text.strip():
            return JDAnalysis(filename=filename)

        text = jd_text[:8000] if len(jd_text) > 8000 else jd_text

        # Route to Llama 3.2 (routine extraction task)
        decision = self.router.route(
            "extract job description requirements",
            task_type_hint="jd_extraction",
        )

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

            # Validate output using Pydantic
            validated = JDAnalysisSchema.model_validate(data)

            print(f"[JDAnalyzer] Pydantic validated JD: {validated.role_title} — "
                  f"{len(validated.required_skills)} required, {len(validated.preferred_skills)} preferred skills")

            return JDAnalysis(
                role_title       = validated.role_title,
                seniority_level  = validated.seniority_level,
                required_skills  = validated.required_skills,
                preferred_skills = validated.preferred_skills,
                experience_years = validated.experience,
                education        = validated.education if isinstance(validated.education, list) else [validated.education],
                certifications   = validated.certifications,
                responsibilities = validated.responsibilities,
                raw_text         = jd_text,
                filename         = filename,
            )

        except Exception as e:
            print(f"[JDAnalyzer] Error or fallback during parsing: {e}")
            return JDAnalysis(
                role_title="Technical Role",
                required_skills=[],
                preferred_skills=[],
                raw_text=jd_text,
                filename=filename,
            )

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
