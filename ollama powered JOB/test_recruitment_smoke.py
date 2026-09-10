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


def test_resume_upload_and_delete():
    from server import app
    import io
    client = app.test_client()

    session_id = "test_sess_dedup_1"

    # 1. Upload 2 resumes
    data = {
        "session_id": session_id,
        "files": [
            (io.BytesIO(b"Resume text for John Doe"), "john_doe.txt"),
            (io.BytesIO(b"Resume text for Jane Smith"), "jane_smith.txt"),
        ]
    }
    res = client.post("/api/recruitment/upload-resumes", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["total_resumes"] == 2
    assert len(res_data["accepted"]) == 2

    # 2. Upload same resume again -> should update/replace, not duplicate!
    data2 = {
        "session_id": session_id,
        "files": [
            (io.BytesIO(b"Updated resume for John Doe"), "john_doe.txt"),
        ]
    }
    res2 = client.post("/api/recruitment/upload-resumes", data=data2, content_type="multipart/form-data")
    assert res2.status_code == 200
    res2_data = res2.get_json()
    assert res2_data["total_resumes"] == 2, f"Expected 2 resumes after dedup, got {res2_data['total_resumes']}"
    assert "john_doe.txt" in res2_data["updated"]

    # 3. Delete single resume
    del_res = client.post("/api/recruitment/delete-resume", json={"session_id": session_id, "filename": "john_doe.txt"})
    assert del_res.status_code == 200
    assert del_res.get_json()["total_resumes"] == 1

    # 4. Clear all resumes
    clr_res = client.post("/api/recruitment/clear-resumes", json={"session_id": session_id})
    assert clr_res.status_code == 200
    assert clr_res.get_json()["total_resumes"] == 0

    print("✓ Resume Upload Deduplication, Single Deletion & Clear All OK")


def test_candidate_deletion_and_clear():
    from recruitment.memory_store import RecruitmentMemory
    mem = RecruitmentMemory()

    session_id = "test_sess_cand_del"
    # Insert candidate, ranking, verification
    with mem._get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO candidates (candidate_id, session_id, name) VALUES (?, ?, ?)", ("c1", session_id, "Cand One"))
        cursor.execute("INSERT OR REPLACE INTO rankings (session_id, candidate_id, rank, total_score) VALUES (?, ?, ?, ?)", (session_id, "c1", 1, 95.0))
        cursor.execute("INSERT INTO verifications (session_id, candidate_id, jd_skill, status) VALUES (?, ?, ?, ?)", (session_id, "c1", "Python", "STRONGLY_SUPPORTED"))
        conn.commit()

    # Delete candidate
    mem.delete_candidate("c1", session_id)
    with mem._get_conn() as conn:
        row = conn.cursor().execute("SELECT * FROM candidates WHERE candidate_id = ?", ("c1",)).fetchone()
        assert row is None
        rank_row = conn.cursor().execute("SELECT * FROM rankings WHERE candidate_id = ?", ("c1",)).fetchone()
        assert rank_row is None

    # Clear screening
    mem.clear_screening(session_id)
    print("✓ SQLite Candidate Deletion & Clear Screening OK")


def test_conflict_detection_high():
    from recruitment.agents.requirement_conflict_analyzer import RequirementConflictAnalyzer
    from recruitment.models import JDAnalysis, ConflictSeverity

    analyzer = RequirementConflictAnalyzer()
    jd = JDAnalysis(
        role_title="Junior AI Engineer",
        seniority_level="Junior",
        experience_years="5+ years",
        required_skills=["Python", "PyTorch"],
    )
    report = analyzer._heuristic_check(jd)
    assert report is not None
    assert report.overall_severity == ConflictSeverity.HIGH
    assert len(report.conflicts) >= 1
    print("✓ Requirement Conflict Detection (HIGH severity) OK")


def test_conflict_detection_none():
    from recruitment.agents.requirement_conflict_analyzer import RequirementConflictAnalyzer
    from recruitment.models import JDAnalysis, ConflictSeverity

    analyzer = RequirementConflictAnalyzer()
    jd = JDAnalysis(
        role_title="Senior AI Engineer",
        seniority_level="Senior",
        experience_years="5-8 years",
        required_skills=["Python", "PyTorch", "Kubernetes"],
    )
    report = analyzer._heuristic_check(jd)
    assert report is None or report.overall_severity == ConflictSeverity.NONE
    print("✓ Requirement Conflict Detection (NONE severity) OK")


def test_pool_coverage_intersection_zero():
    from recruitment.ranking.pool_coverage_analyzer import PoolCoverageAnalyzer
    from recruitment.models import JDAnalysis, CandidateScore, CandidateProfile, SkillMatch

    analyzer = PoolCoverageAnalyzer()
    jd = JDAnalysis(
        role_title="Senior Python Backend Engineer",
        required_skills=["Python", "Kubernetes"],
        experience_years="5+ years",
    )
    # Candidate 1: has Python and 6 yrs exp, but NO Kubernetes
    cand1 = CandidateScore(
        candidate_id="c1",
        candidate_name="Alice",
        skill_matches=[
            SkillMatch(jd_skill="Python", candidate_skill="Python", similarity=1.0, matched=True),
            SkillMatch(jd_skill="Kubernetes", candidate_skill="", similarity=0.0, matched=False),
        ],
        profile=CandidateProfile(candidate_id="c1", name="Alice", total_experience_years=6.0),
    )
    # Candidate 2: has Kubernetes, but NO Python and only 2 yrs exp
    cand2 = CandidateScore(
        candidate_id="c2",
        candidate_name="Bob",
        skill_matches=[
            SkillMatch(jd_skill="Python", candidate_skill="", similarity=0.0, matched=False),
            SkillMatch(jd_skill="Kubernetes", candidate_skill="Kubernetes", similarity=1.0, matched=True),
        ],
        profile=CandidateProfile(candidate_id="c2", name="Bob", total_experience_years=2.0),
    )

    cov = analyzer.analyze(jd, [cand1, cand2])
    assert cov.total_candidates == 2
    assert cov.intersection_count == 0
    assert not cov.has_perfect_match
    python_cov = next(e for e in cov.entries if e.requirement == "Python")
    assert python_cov.count == 1
    assert python_cov.percentage == 50.0
    print("✓ Pool Coverage Analyzer (intersection == 0) OK")


def test_pool_coverage_intersection_nonzero():
    from recruitment.ranking.pool_coverage_analyzer import PoolCoverageAnalyzer
    from recruitment.models import JDAnalysis, CandidateScore, CandidateProfile, SkillMatch

    analyzer = PoolCoverageAnalyzer()
    jd = JDAnalysis(
        role_title="Backend Engineer",
        required_skills=["Python", "SQL"],
        experience_years="2+ years",
    )
    cand = CandidateScore(
        candidate_id="c1",
        candidate_name="Charlie",
        skill_matches=[
            SkillMatch(jd_skill="Python", candidate_skill="Python", similarity=1.0, matched=True),
            SkillMatch(jd_skill="SQL", candidate_skill="SQL", similarity=1.0, matched=True),
        ],
        profile=CandidateProfile(candidate_id="c1", name="Charlie", total_experience_years=3.0),
    )
    cov = analyzer.analyze(jd, [cand])
    assert cov.total_candidates == 1
    assert cov.intersection_count == 1
    assert cov.has_perfect_match
    print("✓ Pool Coverage Analyzer (intersection > 0) OK")


def test_tradeoff_shortlist_ordering():
    from recruitment.ranking.pool_coverage_analyzer import PoolCoverageAnalyzer
    from recruitment.ranking.tradeoff_shortlist_builder import TradeOffShortlistBuilder
    from recruitment.models import JDAnalysis, CandidateScore, CandidateProfile, SkillMatch

    jd = JDAnalysis(
        role_title="MLOps Engineer",
        required_skills=["Python", "Kubernetes", "Docker"],
        experience_years="3+ years",
    )

    # Candidate 1: Missing only 1 requirement (Docker)
    cand1 = CandidateScore(
        candidate_id="c1",
        candidate_name="Dave (1 unmet)",
        total_score=80.0,
        skill_matches=[
            SkillMatch(jd_skill="Python", candidate_skill="Python", similarity=1.0, matched=True),
            SkillMatch(jd_skill="Kubernetes", candidate_skill="Kubernetes", similarity=1.0, matched=True),
            SkillMatch(jd_skill="Docker", candidate_skill="", similarity=0.0, matched=False),
        ],
        profile=CandidateProfile(candidate_id="c1", name="Dave (1 unmet)", total_experience_years=4.0),
    )

    # Candidate 2: Missing 2 requirements (Kubernetes and Docker)
    cand2 = CandidateScore(
        candidate_id="c2",
        candidate_name="Eve (2 unmet)",
        total_score=85.0,  # Higher raw score, but more compromises!
        skill_matches=[
            SkillMatch(jd_skill="Python", candidate_skill="Python", similarity=1.0, matched=True),
            SkillMatch(jd_skill="Kubernetes", candidate_skill="", similarity=0.0, matched=False),
            SkillMatch(jd_skill="Docker", candidate_skill="", similarity=0.0, matched=False),
        ],
        profile=CandidateProfile(candidate_id="c2", name="Eve (2 unmet)", total_experience_years=4.0),
    )

    cov_analyzer = PoolCoverageAnalyzer()
    coverage = cov_analyzer.analyze(jd, [cand1, cand2])

    builder = TradeOffShortlistBuilder()
    shortlist = builder.build([cand1, cand2], jd, coverage)

    assert not shortlist.has_perfect_match
    assert len(shortlist.compromise_candidates) == 2
    # Dave (unmet=1) must be ranked ahead of Eve (unmet=2)
    assert shortlist.compromise_candidates[0].candidate_id == "c1"
    assert shortlist.compromise_candidates[0].unmet_count == 1
    assert shortlist.compromise_candidates[1].candidate_id == "c2"
    assert shortlist.compromise_candidates[1].unmet_count == 2
    print("✓ Trade-Off Shortlist Ordering (fewest compromises first) OK")


def test_candidate_comparator_comparison():
    from recruitment.ranking.comparator import CandidateComparator
    from recruitment.models import CandidateScore, CandidateProfile, VerificationResult, VerificationStatus, Claim, JDAnalysis

    v1 = [
        VerificationResult(
            claim=Claim(skill="Go"),
            jd_skill="Go",
            status=VerificationStatus.STRONGLY_SUPPORTED,
            explanation="5 years production Go experience.",
        ),
        VerificationResult(
            claim=Claim(skill="Kubernetes"),
            jd_skill="Kubernetes",
            status=VerificationStatus.PARTIALLY_SUPPORTED,
            explanation="Familiar with basic kubectl.",
        )
    ]
    v2 = [
        VerificationResult(
            claim=Claim(skill="Go"),
            jd_skill="Go",
            status=VerificationStatus.NOT_MENTIONED,
            explanation="No Go mentioned.",
        ),
        VerificationResult(
            claim=Claim(skill="Kubernetes"),
            jd_skill="Kubernetes",
            status=VerificationStatus.STRONGLY_SUPPORTED,
            explanation="CKA certified, managed clusters.",
        )
    ]

    cand1 = CandidateScore(
        candidate_id="c1",
        candidate_name="David Miller",
        total_score=92.0,
        skill_breakdown=v1,
        profile=CandidateProfile(candidate_id="c1", name="David Miller", total_experience_years=6.0),
    )
    cand2 = CandidateScore(
        candidate_id="c2",
        candidate_name="Sarah Chen",
        total_score=87.0,
        skill_breakdown=v2,
        profile=CandidateProfile(candidate_id="c2", name="Sarah Chen", total_experience_years=5.0),
    )
    jd = JDAnalysis(role_title="Lead Cloud Engineer", required_skills=["Go", "Kubernetes"])

    comp = CandidateComparator()
    res = comp.generate_comparison(cand1, cand2, jd)

    # 1. Check top-level convenience properties
    assert res["candidate_a_name"] == "David Miller"
    assert res["candidate_b_name"] == "Sarah Chen"
    assert res["candidate_a_score"] == 92.0
    assert res["candidate_b_score"] == 87.0
    assert res["candidate_a_exp"] == 6.0
    assert res["candidate_b_exp"] == 5.0
    assert res["winner"] == "David Miller"
    assert "narrative" in res and len(res["narrative"]) > 0
    assert "tradeoff" in res and len(res["tradeoff"]) > 0

    # 2. Check skill comparison rows
    sc_map = {row["skill"]: row for row in res["skill_comparison"]}
    assert "Go" in sc_map
    assert "Kubernetes" in sc_map

    go_row = sc_map["Go"]
    assert go_row["a_status"] == "STRONGLY_SUPPORTED"
    assert go_row["b_status"] == "NOT_MENTIONED"
    assert go_row["favors"] == "A"

    k8s_row = sc_map["Kubernetes"]
    assert k8s_row["a_status"] == "PARTIALLY_SUPPORTED"
    assert k8s_row["b_status"] == "STRONGLY_SUPPORTED"
    assert k8s_row["favors"] == "B"

    # 3. Test dictionary input compatibility (simulating SQLite retrieval)
    res_dict = comp.generate_comparison(cand1.to_dict(), cand2.to_dict(), jd.to_dict())
    assert res_dict["candidate_a_name"] == "David Miller"
    assert res_dict["candidate_b_name"] == "Sarah Chen"
    assert res_dict["candidate_a_score"] == 92.0
    assert res_dict["candidate_b_score"] == 87.0
    assert res_dict["candidate_a_exp"] == 6.0
    assert res_dict["candidate_b_exp"] == 5.0

    # 4. Test Flask /api/recruitment/compare endpoint
    from server import app, _sessions
    from recruitment.orchestrator import ScreeningResult
    from recruitment.models import RankedList, RankedCandidate
    client = app.test_client()

    rk1 = RankedCandidate(rank=1, score=cand1, tradeoff_note="Top candidate")
    rk2 = RankedCandidate(rank=2, score=cand2, tradeoff_note="Second candidate")
    rl = RankedList(candidates=[rk1, rk2], jd_role="Lead Cloud Engineer", total_analyzed=2)
    _sessions["test_run_comp"] = {
        "result": ScreeningResult(ranked_list=rl, jd_analysis=jd),
        "done": True
    }

    resp = client.post("/api/recruitment/compare", json={
        "run_id": "test_run_comp",
        "candidate_a": "c1",
        "candidate_b": "c2",
    })
    assert resp.status_code == 200
    comp_json = resp.get_json()
    assert comp_json["candidate_a_name"] == "David Miller"
    assert comp_json["candidate_b_name"] == "Sarah Chen"
    assert comp_json["candidate_a_score"] == 92.0
    assert comp_json["candidate_b_score"] == 87.0
    assert comp_json["candidate_a_exp"] == 6.0
    assert comp_json["candidate_b_exp"] == 5.0
    assert comp_json["winner"] == "David Miller"
    assert len(comp_json["skill_comparison"]) == 2
    assert comp_json["skill_comparison"][0]["favors"] in ("A", "B", "")

    print("✓ Candidate Comparator Comparison & Flask /api/recruitment/compare endpoint OK")


if __name__ == "__main__":
    print("\nRunning ARIA Core — Talent Screening Smoke Tests...")
    test_doc_processor()
    test_pydantic_schemas()
    test_scorer()
    test_gap_analyzer()
    test_sqlite_memory()
    test_router()
    test_flask_app()
    test_resume_upload_and_delete()
    test_candidate_deletion_and_clear()
    test_conflict_detection_high()
    test_conflict_detection_none()
    test_pool_coverage_intersection_zero()
    test_pool_coverage_intersection_nonzero()
    test_tradeoff_shortlist_ordering()
    test_candidate_comparator_comparison()
    print("\nALL SMOKE TESTS PASSED SUCCESSFULLY! 🚀\n")

