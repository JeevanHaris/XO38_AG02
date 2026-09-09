"""
RecruitScreen / ARIA Core — Evidence Retrieval Agent
───────────────────────────────────────────────────
Fast, section-aware evidence retrieval without Sentence Transformers or FAISS.

Pulls relevant evidence passages across:
  - Projects
  - Experience Entries
  - Certifications
  - Specific resume text paragraphs
"""

import re
from ..models import Claim, Evidence, CandidateProfile


class EvidenceRetrievalAgent:
    """
    Retrieves evidence passages from the candidate's application supporting a claim.
    Operates without heavy embedding models, searching structured sections and text.
    """

    TOP_K = 4

    def __init__(self):
        pass

    def build_index(self, profile: CandidateProfile) -> int:
        """Lightweight no-op to maintain pipeline interface compatibility."""
        return len(profile.raw_text.split()) if profile.raw_text else 0

    def retrieve(self, claim: Claim, profile: CandidateProfile) -> list[Evidence]:
        """
        Retrieve evidence for a single claim from candidate's profile.
        """
        evidence_list = []
        target_skill = (claim.jd_skill or claim.skill or "").strip().lower()
        if not target_skill:
            return []

        skill_terms = [target_skill]
        # Basic common synonyms
        if target_skill == "postgresql" or target_skill == "postgres":
            skill_terms.extend(["postgres", "postgresql", "psql", "sql"])
        elif target_skill in ("js", "javascript"):
            skill_terms.extend(["javascript", "js", "ecmascript", "es6", "frontend"])
        elif target_skill in ("python", "py"):
            skill_terms.extend(["python", "fastapi", "django", "flask"])
        elif "rest" in target_skill or "api" in target_skill:
            skill_terms.extend(["rest", "api", "apis", "fastapi", "endpoints", "graphql", "backend"])
        elif "react" in target_skill:
            skill_terms.extend(["react", "reactjs", "react.js", "frontend", "redux"])
        elif "docker" in target_skill:
            skill_terms.extend(["docker", "container", "dockerfile", "compose"])
        elif "kubernetes" in target_skill or "k8s" in target_skill:
            skill_terms.extend(["kubernetes", "k8s", "helm"])

        # 1. Check Certifications (Highest quality evidence)
        for cert in profile.certifications:
            c_low = cert.lower()
            if any(term in c_low for term in skill_terms):
                evidence_list.append(Evidence(
                    chunk_text=f"Certification: {cert}",
                    similarity_score=0.98,
                    source_section="Certifications",
                ))

        # 2. Check Projects (Strong evidence)
        for proj in profile.projects:
            p_low = proj.lower()
            if any(term in p_low for term in skill_terms):
                evidence_list.append(Evidence(
                    chunk_text=f"Project: {proj}",
                    similarity_score=0.92,
                    source_section="Projects",
                ))

        # 3. Check Experience Entries (Strong evidence)
        for exp in profile.experience_entries:
            combined = f"{exp.title} at {exp.company}: {exp.description}".lower()
            if any(term in combined for term in skill_terms):
                evidence_list.append(Evidence(
                    chunk_text=f"{exp.title} at {exp.company} ({exp.duration}): {exp.description}",
                    similarity_score=0.88,
                    source_section="Work Experience",
                ))

        # 4. Check Raw Claims
        for c in profile.raw_claims:
            c_low = c.lower()
            if any(term in c_low for term in skill_terms):
                evidence_list.append(Evidence(
                    chunk_text=f"Achievement: {c}",
                    similarity_score=0.82,
                    source_section="Claims",
                ))

        # 5. Check Raw Text Paragraphs if not enough evidence yet
        if len(evidence_list) < 2 and profile.raw_text:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", profile.raw_text) if len(p.strip()) > 30]
            for p in paragraphs:
                p_low = p.lower()
                if any(term in p_low for term in skill_terms):
                    # Avoid duplicate text
                    if not any(p[:40] in ev.chunk_text for ev in evidence_list):
                        evidence_list.append(Evidence(
                            chunk_text=p[:300],
                            similarity_score=0.75,
                            source_section="Resume Text",
                        ))
                if len(evidence_list) >= self.TOP_K:
                    break

        # 6. If only listed in Skills section
        skills_lower = [s.lower() for s in profile.skills]
        if any(term in s for s in skills_lower for term in skill_terms):
            if not evidence_list:
                evidence_list.append(Evidence(
                    chunk_text=f"Mentioned in Skills section: {claim.jd_skill}",
                    similarity_score=0.50,
                    source_section="Skills",
                ))

        # Sort by similarity score
        evidence_list.sort(key=lambda e: e.similarity_score, reverse=True)
        return evidence_list[:self.TOP_K]

    def retrieve_all(
        self,
        claims:  list[Claim],
        profile: CandidateProfile,
    ) -> dict[str, list[Evidence]]:
        """
        Retrieve evidence for all claims in one pass.
        Returns dict mapping claim.jd_skill -> list[Evidence]
        """
        result = {}
        for claim in claims:
            ev = self.retrieve(claim, profile)
            result[claim.jd_skill] = ev
        return result
