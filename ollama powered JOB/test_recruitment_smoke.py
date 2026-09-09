"""
RecruitScreen v1.0 — Smoke Test
Verifies document processor, scorer, comparator, gap analyzer, and server routes.
"""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Suppress HuggingFace symlinks warning
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from recruitment.models import (
    JDAnalysis, CandidateProfile, Claim, Evidence,
    VerificationResult, VerificationStatus, CandidateScore, SkillMatch
)
from recruitment.ranking.scorer import CandidateScorer
from recruitment.ranking.gap_analyzer import RequirementGapAnalyzer
from recruitment.doc_processor import DocumentProcessor

def test_doc_processor():
    proc = DocumentProcessor()
    # Test text validation
    ok, err = proc.validate_file("resume.pdf")
    assert ok, f"PDF should be valid: {err}"
    
    ok, err = proc.validate_file("malicious.exe")
    assert not ok, "EXE should be rejected"
    print("✓ DocumentProcessor validation OK")

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
    # Python has 2/2 coverage -> ADEQUATE
    python_gap = next(g for g in report.skill_gaps if g.skill == "Python")
    assert python_gap.percentage == 100.0
    
    # Rust has 0/2 coverage -> HIGH_RISK
    rust_gap = next(g for g in report.skill_gaps if g.skill == "Rust")
    assert rust_gap.percentage == 0.0
    print("✓ RequirementGapAnalyzer OK")

def test_flask_app():
    from server import app
    client = app.test_client()
    
    # Health endpoint
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "RecruitScreen v1.0"
    print("✓ Flask /api/health OK")

if __name__ == "__main__":
    print("\nRunning RecruitScreen v1.0 Smoke Tests...")
    test_doc_processor()
    test_scorer()
    test_gap_analyzer()
    test_flask_app()
    print("\nALL SMOKE TESTS PASSED SUCCESSFULLY! 🚀\n")
