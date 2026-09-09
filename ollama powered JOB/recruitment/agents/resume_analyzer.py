"""
RecruitScreen / ARIA Core — Resume Analyzer Agent
────────────────────────────────────────────────
Sends each candidate resume to Llama 3.2 and validates structured output using Pydantic.

Schema:
{
  "candidate": "Candidate A",
  "skills": ["Python", "HTML", "CSS", "React"],
  "certifications": ["Python Certification"],
  "projects": ["Built a Python web application"],
  "education": ["B.S. Computer Science"],
  "experience": [...],
  "claims": [...]
}
"""

import json
import re
from typing import List, Union, Any
from pydantic import BaseModel, Field, field_validator
from ..models import CandidateProfile, ExperienceEntry


class ExperienceItemSchema(BaseModel):
    title: str = Field(default="")
    company: str = Field(default="")
    duration: str = Field(default="")
    description: str = Field(default="")


class ResumeAnalysisSchema(BaseModel):
    """Pydantic schema to validate candidate resume extraction from Llama 3.2."""
    model_config = {"populate_by_name": True, "extra": "ignore"}

    name: str = Field(default="Candidate", alias="candidate")
    email: str = Field(default="")
    phone: str = Field(default="")
    skills: List[str] = Field(default_factory=list)
    experience_entries: List[Any] = Field(default_factory=list, alias="experience")
    total_experience_years: float = Field(default=0.0)
    projects: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    raw_claims: List[str] = Field(default_factory=list, alias="claims")

    @field_validator("name", mode="before")
    @classmethod
    def extract_name(cls, v, info):
        if not v or v == "Candidate":
            return v or "Candidate"
        return str(v).strip()

    @field_validator("skills", "projects", "education", "certifications", "raw_claims", mode="before")
    @classmethod
    def clean_str_list(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            cleaned = []
            seen = set()
            for item in v:
                s = str(item).strip()
                if s and s.lower() not in seen:
                    seen.add(s.lower())
                    cleaned.append(s)
            return cleaned
        return []

    @field_validator("total_experience_years", mode="before")
    @classmethod
    def clean_exp_years(cls, v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            match = re.search(r"(\d+(?:\.\d+)?)", v)
            if match:
                return float(match.group(1))
        return 0.0


SYSTEM_PROMPT = """You are an expert resume parser. Extract structured information from resumes.
Extract ONLY what is explicitly stated. Do NOT fabricate or assume anything.
Output valid JSON only — no markdown, no explanation."""


EXTRACTION_PROMPT = """Parse this resume and extract structured candidate information.

Resume:
\"\"\"
{resume_text}
\"\"\"

Return a JSON object with EXACTLY these fields:
{{
  "name": "Candidate Name",
  "email": "candidate email or empty string",
  "phone": "phone number or empty string",
  "skills": ["Python", "HTML", "CSS", "React", "REST APIs"],
  "experience_entries": [
    {{
      "title": "Software Engineer",
      "company": "Tech Corp",
      "duration": "2021 - 2023",
      "description": "Built backend services and APIs"
    }}
  ],
  "total_experience_years": 2.0,
  "projects": [
    "Built a Python web application with FastAPI",
    "Developed React dashboard"
  ],
  "education": [
    "B.S. in Computer Science"
  ],
  "certifications": [
    "Python Certification"
  ],
  "raw_claims": [
    "Built scalable backend services in Python",
    "Optimized database queries by 30%"
  ]
}}

Rules:
- skills: Include all specific technical skills
- projects: Notable projects mentioning tech used
- raw_claims: Specific achievements or technical claims
- Output ONLY valid JSON, nothing else"""


class ResumeAnalyzerAgent:
    """Extracts structured profile from resume text using Llama 3.2 and validates with Pydantic."""

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
        if not resume_text or not resume_text.strip():
            return CandidateProfile(
                candidate_id=candidate_id,
                name=candidate_name or "Unknown Candidate",
                filename=filename,
            )

        text = resume_text[:10000] if len(resume_text) > 10000 else resume_text

        # Route to Llama 3.2 (routine extraction task)
        decision = self.router.route(
            "extract resume skills and experience",
            task_type_hint="resume_extraction",
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
            raw = response.content.strip()
            data = self._parse_json(raw)

            # Accept both 'candidate' and 'name'
            if "candidate" in data and "name" not in data:
                data["name"] = data["candidate"]
            if "experience" in data and "experience_entries" not in data:
                data["experience_entries"] = data["experience"]
            if "claims" in data and "raw_claims" not in data:
                data["raw_claims"] = data["claims"]

            # Validate using Pydantic
            validated = ResumeAnalysisSchema.model_validate(data)

            # Format experience entries
            exp_entries = []
            for item in validated.experience_entries:
                if isinstance(item, dict):
                    exp_entries.append(ExperienceEntry(
                        title=str(item.get("title", "")),
                        company=str(item.get("company", "")),
                        duration=str(item.get("duration", "")),
                        description=str(item.get("description", "")),
                    ))
                elif isinstance(item, str) and item.strip():
                    exp_entries.append(ExperienceEntry(
                        title=item.strip(),
                        company="",
                        duration="",
                        description=item.strip(),
                    ))

            final_name = validated.name
            if final_name in ("Candidate", "Candidate Name", "Unknown", ""):
                final_name = candidate_name or f"Candidate {candidate_id[:6]}"

            print(f"[ResumeAnalyzer] Pydantic validated profile: {final_name} — "
                  f"{len(validated.skills)} skills, {len(exp_entries)} roles, "
                  f"{len(validated.projects)} projects, {len(validated.certifications)} certs")

            return CandidateProfile(
                candidate_id           = candidate_id,
                name                   = final_name,
                email                  = validated.email,
                phone                  = validated.phone,
                skills                 = validated.skills,
                experience_entries     = exp_entries,
                total_experience_years = validated.total_experience_years,
                projects               = validated.projects,
                education              = validated.education,
                certifications         = validated.certifications,
                raw_claims             = validated.raw_claims,
                raw_text               = resume_text,
                filename               = filename,
            )

        except Exception as e:
            print(f"[ResumeAnalyzer] Fallback parse for {candidate_name}: {e}")
            return CandidateProfile(
                candidate_id=candidate_id,
                name=candidate_name or "Candidate",
                raw_text=resume_text,
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
