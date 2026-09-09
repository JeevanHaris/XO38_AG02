"""
RecruitScreen / ARIA Core — Recruitment Orchestrator
────────────────────────────────────────────────────
Agentic orchestrator coordinating the lean, two-model candidate screening pipeline.

Pipeline:
  1. Process Documents (PyMuPDF / docx clean text extraction)
  2. Analyze JD (Llama 3.2 + Pydantic validation)
  3. Analyze Resumes (Llama 3.2 + Pydantic validation)
  4. Extract Skill Claims (Llama 3.2)
  5. Retrieve Evidence (Fast section-aware extraction)
  6. Verify Evidence (🟢 Strongly Supported, 🟡 Partially Supported, 🔴 Unsupported, ⚪ Not Mentioned)
  7. Semantic Skill Matching (Taxonomy + normalized matching)
  8. Calculate Deterministic Scores (Python: 40% Required, 25% Experience, 20% Evidence, 10% Preferred, 5% Education)
  9. Rank & Compare Top Candidates (Groq trade-off reasoning)
  10. Identify Skill Gaps (Python pool stats + Groq advisory summary)
  11. Persist to SQLite Recruitment Memory
"""

import time
import uuid
from typing import Callable, Optional

from .models import (
    ScreeningResult, PipelineStage, CandidateProfile,
)
from .doc_processor import DocumentProcessor
from .agents.jd_analyzer        import JDAnalyzerAgent
from .agents.resume_analyzer    import ResumeAnalyzerAgent
from .agents.claim_extractor    import ClaimExtractorAgent
from .agents.evidence_retrieval import EvidenceRetrievalAgent
from .agents.evidence_verifier  import EvidenceVerifierAgent
from .agents.skill_matcher      import SemanticSkillMatcher
from .ranking.scorer            import CandidateScorer
from .ranking.comparator        import CandidateComparator
from .ranking.gap_analyzer      import RequirementGapAnalyzer
from .memory_store              import RecruitmentMemory


class RecruitmentOrchestrator:
    """
    Coordinates the agentic talent screening pipeline.
    Progress is reported via an optional callback so the server streams updates.
    """

    def __init__(self, gateway, router, db_path: str = None):
        self.gateway = gateway
        self.router  = router

        # Initialize all agents & services
        self.doc_processor      = DocumentProcessor()
        self.jd_analyzer        = JDAnalyzerAgent(gateway, router)
        self.resume_analyzer    = ResumeAnalyzerAgent(gateway, router)
        self.claim_extractor    = ClaimExtractorAgent(gateway, router)
        self.evidence_retrieval = EvidenceRetrievalAgent()
        self.evidence_verifier  = EvidenceVerifierAgent(gateway, router)
        self.skill_matcher      = SemanticSkillMatcher(gateway, router)
        self.scorer             = CandidateScorer()
        self.comparator         = CandidateComparator(gateway, router)
        self.gap_analyzer       = RequirementGapAnalyzer(gateway, router)
        self.memory             = RecruitmentMemory(db_path=db_path)

    def run_screening(
        self,
        jd_file:      tuple[str, bytes],             # (filename, bytes)
        resume_files: list[tuple[str, bytes]],        # [(filename, bytes), ...]
        session_id:   str = None,
        progress_cb:  Callable[[ScreeningResult], None] = None,
    ) -> ScreeningResult:
        """
        Run the full agentic screening pipeline.
        """
        t0         = time.time()
        session_id = session_id or str(uuid.uuid4())
        result     = ScreeningResult(session_id=session_id)

        def update(stage: PipelineStage, pct: float, msg: str):
            result.pipeline_stage = stage
            result.progress_pct   = pct
            result.progress_log.append(f"[{pct:.0f}%] {msg}")
            print(f"[Orchestrator] {pct:.0f}% — {msg}")
            if progress_cb:
                try:
                    progress_cb(result)
                except Exception:
                    pass

        try:
            # ── Stage 1: Process Documents ────────────────────────────
            update(PipelineStage.PROCESSING_DOCS, 5, "Processing documents (PyMuPDF & python-docx)...")

            jd_filename, jd_bytes = jd_file
            jd_doc = self.doc_processor.process_jd(jd_filename, jd_bytes)
            if jd_doc["error"]:
                result.error = f"JD processing failed: {jd_doc['error']}"
                result.pipeline_stage = PipelineStage.FAILED
                return result

            resume_docs = self.doc_processor.batch_process_resumes(resume_files)
            valid_resumes = [r for r in resume_docs if not r["error"]]

            if not valid_resumes:
                result.error = "No resumes could be processed successfully."
                result.pipeline_stage = PipelineStage.FAILED
                return result

            update(PipelineStage.PROCESSING_DOCS, 10,
                   f"Extracted clean text for JD + {len(valid_resumes)}/{len(resume_docs)} resumes")

            # ── Stage 2: Analyze JD (Llama 3.2 + Pydantic) ────────────
            update(PipelineStage.ANALYZING_JD, 15, "Analyzing Job Description with Llama 3.2...")
            jd_analysis = self.jd_analyzer.analyze(jd_doc["raw_text"], jd_filename)
            result.jd_analysis = jd_analysis

            if not jd_analysis.required_skills:
                update(PipelineStage.ANALYZING_JD, 20,
                       "⚠ No required skills explicitly extracted. Falling back to key skills.")
            else:
                update(PipelineStage.ANALYZING_JD, 20,
                       f"JD analyzed: {jd_analysis.role_title} — "
                       f"{len(jd_analysis.required_skills)} required, "
                       f"{len(jd_analysis.preferred_skills)} preferred skills")

            # ── Stage 3: Analyze Resumes (Llama 3.2 + Pydantic) ───────
            update(PipelineStage.ANALYZING_RESUMES, 22, "Extracting candidate profiles with Llama 3.2...")
            profiles: list[CandidateProfile] = []

            for i, resume_doc in enumerate(valid_resumes):
                pct  = 22 + (i / len(valid_resumes)) * 18
                name = resume_doc["candidate_name"]
                update(PipelineStage.ANALYZING_RESUMES, pct,
                       f"Analyzing resume: {name} ({i+1}/{len(valid_resumes)})")

                profile = self.resume_analyzer.analyze(
                    resume_text    = resume_doc["raw_text"],
                    candidate_name = name,
                    candidate_id   = resume_doc["candidate_id"],
                    filename       = resume_doc["filename"],
                )
                profiles.append(profile)

            result.candidates = profiles
            update(PipelineStage.ANALYZING_RESUMES, 40,
                   f"Parsed and validated {len(profiles)} candidate profiles")

            # ── Stage 4: Extract Skill Claims (Llama 3.2) ─────────────
            update(PipelineStage.EXTRACTING_CLAIMS, 42, "Extracting skill claims for JD requirements...")
            all_claims: dict[str, list] = {}

            for i, profile in enumerate(profiles):
                pct = 42 + (i / len(profiles)) * 13
                update(PipelineStage.EXTRACTING_CLAIMS, pct,
                       f"Extracting claims: {profile.name} ({i+1}/{len(profiles)})")
                claims = self.claim_extractor.extract(jd_analysis, profile)
                all_claims[profile.candidate_id] = claims

            update(PipelineStage.EXTRACTING_CLAIMS, 55,
                   f"Extracted claims for {len(profiles)} candidates")

            # ── Stage 5 & 6: Retrieve & Verify Evidence ───────────────
            update(PipelineStage.VERIFYING_EVIDENCE, 56, "Verifying candidate evidence (🟢/🟡/🔴/⚪)...")
            all_verifications: dict[str, list] = {}

            for i, profile in enumerate(profiles):
                pct = 56 + (i / len(profiles)) * 20
                update(PipelineStage.VERIFYING_EVIDENCE, pct,
                       f"Verifying evidence for {profile.name} ({i+1}/{len(profiles)})...")

                claims = all_claims.get(profile.candidate_id, [])
                if not claims:
                    all_verifications[profile.candidate_id] = []
                    continue

                # Retrieve evidence passages across sections
                evidence_map = self.evidence_retrieval.retrieve_all(claims, profile)

                # Verify each claim
                verifications = self.evidence_verifier.verify_all(claims, evidence_map)
                all_verifications[profile.candidate_id] = verifications

            update(PipelineStage.VERIFYING_EVIDENCE, 76,
                   f"Verified concrete evidence for {len(profiles)} candidates")

            # ── Stage 7: Semantic Skill Matching ──────────────────────
            update(PipelineStage.MATCHING_SKILLS, 78, "Performing semantic skill matching...")
            all_req_matches:  dict[str, list] = {}
            all_pref_matches: dict[str, list] = {}

            for profile in profiles:
                req_m  = self.skill_matcher.match_required_skills(jd_analysis, profile)
                pref_m = self.skill_matcher.match_preferred_skills(jd_analysis, profile)
                all_req_matches[profile.candidate_id]  = req_m
                all_pref_matches[profile.candidate_id] = pref_m

            update(PipelineStage.MATCHING_SKILLS, 84, "Semantic skill matching complete")

            # ── Stage 8: Score Candidates (Python Deterministic) ──────
            update(PipelineStage.SCORING, 86, "Calculating deterministic Python scores (40/25/20/10/5)...")
            all_scores = []

            for profile in profiles:
                score = self.scorer.score(
                    profile       = profile,
                    jd_analysis   = jd_analysis,
                    verifications = all_verifications.get(profile.candidate_id, []),
                    skill_matches = all_req_matches.get(profile.candidate_id, []),
                    pref_matches  = all_pref_matches.get(profile.candidate_id, []),
                )
                all_scores.append(score)
                print(f"[Orchestrator] Score {profile.name}: {score.total_score:.1f}")

            update(PipelineStage.SCORING, 90, f"Scored {len(all_scores)} candidates deterministically")

            # ── Stage 9: Rank Candidates & Trade-off Analysis (Groq) ──
            update(PipelineStage.RANKING, 92, "Ranking candidates & generating Groq trade-off analysis...")
            ranked_list        = self.comparator.rank(all_scores, jd_analysis)
            result.ranked_list = ranked_list
            top_name = ranked_list.candidates[0].score.candidate_name if ranked_list.candidates else "N/A"
            update(PipelineStage.RANKING, 95, f"Ranking complete. Top candidate: {top_name}")

            # ── Stage 10: Requirement Gap Analysis (Python + Groq) ────
            update(PipelineStage.GAP_ANALYSIS, 96, "Calculating requirement gaps across applicant pool...")
            gap_report        = self.gap_analyzer.analyze(jd_analysis, all_scores)
            result.gap_report = gap_report
            update(PipelineStage.GAP_ANALYSIS, 98,
                   f"Gap analysis complete: {len(gap_report.high_risk_skills)} skill shortages identified")

            # ── Stage 11: Persist to SQLite Recruitment Memory ────────
            try:
                self.memory.save_screening_result(result)
            except Exception as e:
                print(f"[Orchestrator] Warning: Could not save to SQLite memory: {e}")

            # ── Done ──────────────────────────────────────────────────
            result.total_time_secs = time.time() - t0
            result.pipeline_stage  = PipelineStage.COMPLETE
            result.progress_pct    = 100.0
            result.progress_log.append(
                f"[100%] ✓ Screening complete in {result.total_time_secs:.1f}s"
            )
            if progress_cb:
                progress_cb(result)

            print(f"[Orchestrator] ✓ Complete in {result.total_time_secs:.1f}s. "
                  f"{len(profiles)} candidates analyzed.")
            return result

        except Exception as e:
            import traceback
            result.error           = str(e)
            result.pipeline_stage  = PipelineStage.FAILED
            result.total_time_secs = time.time() - t0
            print(f"[Orchestrator] ✗ Pipeline failed: {e}")
            traceback.print_exc()
            return result
