"""
RecruitScreen / ARIA Core — Smoke Test Suite
Verifies:
  1. PyMuPDF Document Processor
  2. Pydantic JD & Resume validation
  3. Deterministic Python Scorer (40/25/20/10/5)
  4. Requirement Gap Analyzer
  5. SQLite Recruitment Memory
  6. Smart Router Two-Model Architecture
  7. Flask App & Health Check
"""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from recruitment.models import (
    JDAnalysis, CandidateProfile, Claim, Evidence,
    VerificationResult, VerificationStatus, CandidateScore, SkillMatch
)
from recruitment.ranking.scorer import CandidateScorer
from recruitment.ranking.gap_analyzer import RequirementGapAnalyzer
from recruitment.doc_processor import DocumentProcessor
from recruitment.agents.jd_analyzer import JDAnalysisSchema
from recruitment.agents.resume_analyzer import ResumeAnalysisSchema
from recruitment.memory_store import RecruitmentMemory
from router import ModelRouter


def test_doc_processor():
    proc = DocumentProcessor()
    ok, err = proc.validate_file("resume.pdf")
    assert ok, f"PDF should be valid: {err}"
    
    ok, err = proc.validate_file("malicious.exe")
    assert not ok, "EXE should be rejected"
    print("✓ DocumentProcessor (PyMuPDF & python-docx) validation OK")


def test_pydantic_schemas():
    # JD Schema validation
    jd_raw = {
        "role_title": "Web Developer",
        "seniority_level": "Junior",
        "required_skills": ["HTML", "CSS", "JavaScript", "REST APIs"],
        "preferred_skills": ["React", "Python", "PostgreSQL"],
        "experience": "0-2 years",
        "education": "Computer Science or related"
    }
    jd_valid = JDAnalysisSchema.model_validate(jd_raw)
    assert len(jd_valid.required_skills) == 4
    assert jd_valid.experience == "0-2 years"

    # Resume Schema validation
    resume_raw = {
        "candidate": "Candidate A",
        "skills": ["Python", "HTML", "CSS", "React"],
        "certifications": ["Python Certification"],
        "projects": ["Built a Python web application"],
        "experience": [{"title": "Junior Dev", "company": "Acme", "duration": "1 yr", "description": "Web apps"}],
    }
    res_valid = ResumeAnalysisSchema.model_validate(resume_raw)
    assert res_valid.name == "Candidate A"
    assert "Python" in res_valid.skills
    assert len(res_valid.projects) == 1
    print("✓ Pydantic JD & Resume Schemas validation OK")


def test_scorer():
    scorer = CandidateScorer()
    
    jd = JDAnalysis(
        role_title="Senior Python Backend Engineer",
        seniority_level="Senior",
        required_skills=["Python", "PostgreSQL", "Docker"],
        preferred_skills=["Kubernetes", "Redis"],
        experience_years="3-5 years",
        education=["Bachelor's in Computer Science"],
    )
    
    cand = CandidateProfile(
        candidate_id="c_test_1",
        name="Alex Morgan",
        skills=["Python", "PostgreSQL", "Docker", "Kubernetes"],
        total_experience_years=4.5,
        education=["Bachelor of Science in Computer Science"],
    )
    
    verifications = [
        VerificationResult(
            claim=Claim(skill="Python", statement="Built Python REST APIs"),
            jd_skill="Python",
            status=VerificationStatus.STRONGLY_SUPPORTED,
            confidence_score=0.95,
            evidence=[Evidence(chunk_text="Built Python REST APIs using FastAPI.", similarity_score=0.92)],
            explanation="Clear direct evidence of Python experience."
        ),
        VerificationResult(
            claim=Claim(skill="PostgreSQL", statement="Optimized DB queries"),
            jd_skill="PostgreSQL",
            status=VerificationStatus.STRONGLY_SUPPORTED,
            confidence_score=0.90,
            evidence=[Evidence(chunk_text="Optimized PostgreSQL queries.", similarity_score=0.89)],
            explanation="Direct database experience."
        ),
        VerificationResult(
            claim=Claim(skill="Docker", statement="Used container tools"),
            jd_skill="Docker",
            status=VerificationStatus.PARTIALLY_SUPPORTED,
            confidence_score=0.75,
            evidence=[],
            explanation="Mentioned Docker in passing."
        ),
    ]
    
    skill_matches = [
        SkillMatch(jd_skill="Python", candidate_skill="Python", similarity=1.0, matched=True, match_type="exact"),
        SkillMatch(jd_skill="PostgreSQL", candidate_skill="PostgreSQL", similarity=1.0, matched=True, match_type="exact"),
        SkillMatch(jd_skill="Docker", candidate_skill="Docker", similarity=1.0, matched=True, match_type="exact"),
    ]
    
    score = scorer.score(cand, jd, verifications, skill_matches)
    assert 0 <= score.total_score <= 100, f"Score out of bounds: {score.total_score}"
    assert len(score.component_scores) == 5
    req_comp = next(c for c in score.component_scores if c.name == "Required Skills")
    assert req_comp.score > 0
    print(f"✓ CandidateScorer OK (Alex Morgan score: {score.total_score:.1f}/100)")


def test_gap_analyzer():
    analyzer = RequirementGapAnalyzer()
    
    jd = JDAnalysis(
        role_title="Senior Python Backend Engineer",
        required_skills=["Python", "Kubernetes", "Rust"],
    )
    
    cand1 = CandidateScore(
        candidate_id="1", candidate_name="Alex",
        skill_matches=[
            SkillMatch(jd_skill="Python", matched=True),
            SkillMatch(jd_skill="Kubernetes", matched=True),
            SkillMatch(jd_skill="Rust", matched=False),
        ]
    )
    cand2 = CandidateScore(
        candidate_id="2", candidate_name="Beth",
        skill_matches=[
            SkillMatch(jd_skill="Python", matched=True),
            SkillMatch(jd_skill="Kubernetes", matched=False),
            SkillMatch(jd_skill="Rust", matched=False),
        ]
    )
    
    report = analyzer.analyze(jd, [cand1, cand2])
    assert len(report.skill_gaps) == 3
    python_gap = next(g for g in report.skill_gaps if g.skill == "Python")
    assert python_gap.percentage == 100.0
    
    rust_gap = next(g for g in report.skill_gaps if g.skill == "Rust")
    assert rust_gap.percentage == 0.0
    print("✓ RequirementGapAnalyzer OK")


def test_sqlite_memory():
    mem = RecruitmentMemory()
    assert os.path.exists(mem.db_path)
    mem.save_chat_message("sess_test", "user", "Why is Alex ranked first?")
    mem.save_chat_message("sess_test", "assistant", "Alex has strong Python and PostgreSQL evidence.")
    history = mem.get_chat_history("sess_test")
    assert len(history) >= 2
    print("✓ SQLite RecruitmentMemory persistence OK")


def test_router():
    router = ModelRouter()
    r1 = router.route_task("jd_extraction")
    assert r1.provider == "ollama"
    
    r2 = router.route_task("complex_comparison")
    assert r2.provider == "groq"
    print("✓ Smart Router Two-Model Architecture OK (Llama 3.2 & Groq)")


def test_flask_app():
    from server import app
    client = app.test_client()
    
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["local_model"] == "llama3.2:latest"
    print(f"✓ Flask /api/health OK (Local: {data['local_model']}, Groq: {data['groq_model']})")


if __name__ == "__main__":
    print("\nRunning ARIA Core — Talent Screening Smoke Tests...")
    test_doc_processor()
    test_pydantic_schemas()
    test_scorer()
    test_gap_analyzer()
    test_sqlite_memory()
    test_router()
    test_flask_app()
    print("\nALL SMOKE TESTS PASSED SUCCESSFULLY! 🚀\n")
