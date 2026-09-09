"""
RecruitScreen / ARIA Core — Semantic Skill Matcher
─────────────────────────────────────────────────
Lightweight semantic skill matcher operating WITHOUT Sentence Transformers.

Uses:
  1. Exact and normalized token matching
  2. Technical alias & framework taxonomy (e.g. FastAPI -> REST API)
  3. Optional Llama 3.2 semantic check for ambiguous requirements
"""

import re
from typing import Optional
from ..models import JDAnalysis, CandidateProfile, SkillMatch


TECH_TAXONOMY = {
    "rest api": ["fastapi", "flask", "django", "express", "express.js", "rest apis", "restful", "endpoints", "api development"],
    "rest apis": ["fastapi", "flask", "django", "express", "express.js", "rest api", "restful", "endpoints", "api development"],
    "rest api development": ["fastapi", "flask", "django", "express", "rest apis", "rest api", "api development"],
    "postgresql": ["postgres", "psql", "sql", "relational database"],
    "postgres": ["postgresql", "psql", "sql"],
    "javascript": ["js", "ecmascript", "es6", "frontend", "typescript"],
    "typescript": ["ts", "javascript", "js"],
    "react": ["reactjs", "react.js", "redux", "next.js", "nextjs"],
    "react.js": ["react", "reactjs", "redux"],
    "vue": ["vuejs", "vue.js", "nuxt"],
    "python": ["python3", "py", "fastapi", "django", "flask"],
    "docker": ["containers", "containerization", "docker-compose", "dockerfile"],
    "kubernetes": ["k8s", "container orchestration", "helm"],
    "aws": ["amazon web services", "ec2", "s3", "lambda", "cloud"],
    "gcp": ["google cloud", "google cloud platform"],
    "azure": ["microsoft azure", "cloud"],
    "ci/cd": ["github actions", "gitlab ci", "jenkins", "pipelines"],
    "mongodb": ["mongo", "nosql", "document database"],
    "redis": ["caching", "in-memory db"],
}


class SemanticSkillMatcher:
    """
    Lightweight matcher between JD skills and candidate skills without Sentence Transformers.
    """

    def __init__(self, gateway=None, router=None):
        self.gateway = gateway
        self.router  = router

    def match_required_skills(
        self,
        jd_analysis:  JDAnalysis,
        profile:      CandidateProfile,
    ) -> list[SkillMatch]:
        return self._match_skill_list(
            jd_skills        = jd_analysis.required_skills,
            candidate_skills = profile.skills,
            profile          = profile,
        )

    def match_preferred_skills(
        self,
        jd_analysis:  JDAnalysis,
        profile:      CandidateProfile,
    ) -> list[SkillMatch]:
        return self._match_skill_list(
            jd_skills        = jd_analysis.preferred_skills,
            candidate_skills = profile.skills,
            profile          = profile,
        )

    def _match_skill_list(
        self,
        jd_skills:        list[str],
        candidate_skills: list[str],
        profile:          Optional[CandidateProfile] = None,
    ) -> list[SkillMatch]:
        if not jd_skills:
            return []

        if not candidate_skills and not (profile and profile.raw_text):
            return [
                SkillMatch(
                    jd_skill=s,
                    candidate_skill="",
                    similarity=0.0,
                    matched=False,
                    match_type="none",
                )
                for s in jd_skills
            ]

        cand_skills_lower = {s.lower().strip(): s for s in candidate_skills}
        full_text_lower = (profile.raw_text or "").lower() if profile else ""

        results = []

        for jd_skill in jd_skills:
            jd_clean = jd_skill.lower().strip()

            # 1. Exact string match in skills
            if jd_clean in cand_skills_lower:
                results.append(SkillMatch(
                    jd_skill=jd_skill,
                    candidate_skill=cand_skills_lower[jd_clean],
                    similarity=1.0,
                    matched=True,
                    match_type="exact",
                ))
                continue

            # 2. Substring or word boundary match in candidate skills
            found_sub = False
            for c_low, c_orig in cand_skills_lower.items():
                if jd_clean in c_low or c_low in jd_clean:
                    results.append(SkillMatch(
                        jd_skill=jd_skill,
                        candidate_skill=c_orig,
                        similarity=0.92,
                        matched=True,
                        match_type="substring",
                    ))
                    found_sub = True
                    break
            if found_sub:
                continue

            # 3. Taxonomy / Alias match (e.g. FastAPI -> REST API)
            found_tax = False
            aliases = TECH_TAXONOMY.get(jd_clean, [])
            for alias in aliases:
                # Check candidate skills
                for c_low, c_orig in cand_skills_lower.items():
                    if alias in c_low or c_low in alias:
                        results.append(SkillMatch(
                            jd_skill=jd_skill,
                            candidate_skill=c_orig,
                            similarity=0.88,
                            matched=True,
                            match_type="semantic_taxonomy",
                        ))
                        found_tax = True
                        break
                if found_tax:
                    break

                # Check resume text / projects for the alias
                if not found_tax and full_text_lower and alias in full_text_lower:
                    results.append(SkillMatch(
                        jd_skill=jd_skill,
                        candidate_skill=alias.title(),
                        similarity=0.82,
                        matched=True,
                        match_type="resume_text_match",
                    ))
                    found_tax = True
                    break

            if found_tax:
                continue

            # 4. Check full resume text directly
            if full_text_lower and re.search(r"\b" + re.escape(jd_clean) + r"\b", full_text_lower):
                results.append(SkillMatch(
                    jd_skill=jd_skill,
                    candidate_skill=jd_skill,
                    similarity=0.80,
                    matched=True,
                    match_type="text_presence",
                ))
                continue

            # 5. Fallback: Not matched
            results.append(SkillMatch(
                jd_skill=jd_skill,
                candidate_skill="",
                similarity=0.0,
                matched=False,
                match_type="none",
            ))

        return results
