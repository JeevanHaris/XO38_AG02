"""
RecruitScreen v1.0 — Recruitment Orchestrator
───────────────────────────────────────────────
The agentic brain that coordinates the full screening pipeline.

Pipeline:
  Goal → Plan → Execute → Verify → Continue

Stages:
  1.  Process JD + resumes (DocumentProcessor)
  2.  Analyze JD          (JDAnalyzerAgent)
  3.  Analyze resumes     (ResumeAnalyzerAgent × N)
  4.  Build FAISS indexes (EvidenceRetrievalAgent)
  5.  Extract claims      (ClaimExtractorAgent × N)
  6.  Retrieve evidence   (EvidenceRetrievalAgent × N)
  7.  Verify evidence     (EvidenceVerifierAgent × N × M)
  8.  Semantic matching   (SemanticSkillMatcher × N)
  9.  Score candidates    (CandidateScorer × N)
  10. Rank + compare      (CandidateComparator)
  11. Gap analysis        (RequirementGapAnalyzer)
  12. Return ScreeningResult
"""

import time
import uuid
from typing import Callable

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


class RecruitmentOrchestrator:
    """
    Coordinates the full 11-stage agentic screening pipeline.

    Progress is reported via an optional callback so the server
    can stream updates to the frontend via SSE.
    """

    PIPELINE_STAGES = [
        (PipelineStage.PROCESSING_DOCS,     "Processing documents",        5),
        (PipelineStage.ANALYZING_JD,        "Analyzing job description",   15),
        (PipelineStage.ANALYZING_RESUMES,   "Analyzing resumes",           30),
        (PipelineStage.EXTRACTING_CLAIMS,   "Extracting skill claims",     45),
        (PipelineStage.RETRIEVING_EVIDENCE, "Retrieving evidence",         60),
        (PipelineStage.VERIFYING_EVIDENCE,  "Verifying evidence",          75),
        (PipelineStage.MATCHING_SKILLS,     "Matching skills semantically", 85),
        (PipelineStage.SCORING,             "Scoring candidates",          90),
        (PipelineStage.RANKING,             "Ranking & comparing",         95),
        (PipelineStage.GAP_ANALYSIS,        "Analyzing skill gaps",        98),
    ]

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

        # Initialize all agents
        self.doc_processor       = DocumentProcessor()
        self.jd_analyzer         = JDAnalyzerAgent(gateway, router)
        self.resume_analyzer     = ResumeAnalyzerAgent(gateway, router)
        self.claim_extractor     = ClaimExtractorAgent(gateway, router)
        self.evidence_retrieval  = EvidenceRetrievalAgent()
        self.evidence_verifier   = EvidenceVerifierAgent(gateway, router)
        self.skill_matcher       = SemanticSkillMatcher()
        self.scorer              = CandidateScorer()
        self.comparator          = CandidateComparator(gateway, router)
        self.gap_analyzer        = RequirementGapAnalyzer()

    def run_screening(
        self,
        jd_file:      tuple[str, bytes],             # (filename, bytes)
        resume_files: list[tuple[str, bytes]],        # [(filename, bytes), ...]
        session_id:   str = None,
        progress_cb:  Callable[[ScreeningResult], None] = None,
    ) -> ScreeningResult:
        """
        Run the full agentic screening pipeline.

        Args:
            jd_file:      (filename, file_bytes) for the job description
            resume_files: list of (filename, file_bytes) for resumes
            session_id:   Optional session identifier
            progress_cb:  Optional callback(ScreeningResult) called after each stage

        Returns:
            Complete ScreeningResult
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
            update(PipelineStage.PROCESSING_DOCS, 5, "Processing documents...")

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

            update(PipelineStage.PROCESSING_DOCS, 8,
                   f"Processed JD + {len(valid_resumes)}/{len(resume_docs)} resumes")

            # ── Stage 2: Analyze JD ───────────────────────────────────
            update(PipelineStage.ANALYZING_JD, 12, "Extracting JD requirements...")
            jd_analysis = self.jd_analyzer.analyze(jd_doc["raw_text"], jd_filename)
            result.jd_analysis = jd_analysis

            if not jd_analysis.required_skills:
                update(PipelineStage.ANALYZING_JD, 15,
                       f"⚠ No required skills extracted. Check JD format.")
            else:
                update(PipelineStage.ANALYZING_JD, 15,
                       f"JD analyzed: {jd_analysis.role_title} — "
                       f"{len(jd_analysis.required_skills)} required skills")

            # ── Stage 3: Analyze Resumes ──────────────────────────────
            update(PipelineStage.ANALYZING_RESUMES, 18, "Analyzing candidate resumes...")
            profiles: list[CandidateProfile] = []

            for i, resume_doc in enumerate(valid_resumes):
                pct  = 18 + (i / len(valid_resumes)) * 12
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
            update(PipelineStage.ANALYZING_RESUMES, 30,
                   f"Analyzed {len(profiles)} candidate profiles")

            # ── Stage 4: Build FAISS Indexes (Evidence Infrastructure) ─
            update(PipelineStage.RETRIEVING_EVIDENCE, 32, "Building semantic indexes...")
            for profile in profiles:
                self.evidence_retrieval.build_index(profile)
            update(PipelineStage.RETRIEVING_EVIDENCE, 35,
                   f"Semantic indexes built for {len(profiles)} candidates")

            # ── Stage 5: Extract Claims ────────────────────────────────
            update(PipelineStage.EXTRACTING_CLAIMS, 36, "Extracting skill claims...")
            all_claims: dict[str, list] = {}   # candidate_id → claims

            for i, profile in enumerate(profiles):
                pct = 36 + (i / len(profiles)) * 9
                update(PipelineStage.EXTRACTING_CLAIMS, pct,
                       f"Extracting claims: {profile.name} ({i+1}/{len(profiles)})")
                claims = self.claim_extractor.extract(jd_analysis, profile)
                all_claims[profile.candidate_id] = claims

            update(PipelineStage.EXTRACTING_CLAIMS, 45,
                   f"Claims extracted for {len(profiles)} candidates")

            # ── Stage 6 & 7: Retrieve + Verify Evidence ───────────────
            update(PipelineStage.RETRIEVING_EVIDENCE, 46, "Retrieving & verifying evidence...")
            all_verifications: dict[str, list] = {}   # candidate_id → verifs

            for i, profile in enumerate(profiles):
                pct = 46 + (i / len(profiles)) * 29
                update(PipelineStage.VERIFYING_EVIDENCE, pct,
                       f"Verifying {profile.name} ({i+1}/{len(profiles)})...")

                claims   = all_claims.get(profile.candidate_id, [])
                if not claims:
                    all_verifications[profile.candidate_id] = []
                    continue

                # Retrieve evidence for all claims at once
                evidence_map = self.evidence_retrieval.retrieve_all(claims, profile)

                # Verify each claim
                verifications = self.evidence_verifier.verify_all(claims, evidence_map)
                all_verifications[profile.candidate_id] = verifications

            update(PipelineStage.VERIFYING_EVIDENCE, 75,
                   f"Evidence verified for {len(profiles)} candidates")

            # ── Stage 8: Semantic Skill Matching ──────────────────────
            update(PipelineStage.MATCHING_SKILLS, 76, "Semantic skill matching...")
            all_req_matches:  dict[str, list] = {}
            all_pref_matches: dict[str, list] = {}

            for profile in profiles:
                req_m  = self.skill_matcher.match_required_skills(jd_analysis, profile)
                pref_m = self.skill_matcher.match_preferred_skills(jd_analysis, profile)
                all_req_matches[profile.candidate_id]  = req_m
                all_pref_matches[profile.candidate_id] = pref_m

            update(PipelineStage.MATCHING_SKILLS, 85,
                   "Skill matching complete")

            # ── Stage 9: Score Candidates ─────────────────────────────
            update(PipelineStage.SCORING, 86, "Scoring candidates...")
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

            update(PipelineStage.SCORING, 90, f"Scored {len(all_scores)} candidates")

            # ── Stage 10: Rank + Compare ──────────────────────────────
            update(PipelineStage.RANKING, 91, "Ranking candidates...")
            ranked_list       = self.comparator.rank(all_scores, jd_analysis)
            result.ranked_list = ranked_list
            update(PipelineStage.RANKING, 95,
                   f"Rankings complete. Top: {ranked_list.candidates[0].score.candidate_name if ranked_list.candidates else 'N/A'}")

            # ── Stage 11: Gap Analysis ────────────────────────────────
            update(PipelineStage.GAP_ANALYSIS, 96, "Analyzing skill gaps...")
            gap_report        = self.gap_analyzer.analyze(jd_analysis, all_scores)
            result.gap_report = gap_report
            update(PipelineStage.GAP_ANALYSIS, 98,
                   f"Gap analysis: {len(gap_report.high_risk_skills)} high-risk skills")

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
            result.error          = str(e)
            result.pipeline_stage = PipelineStage.FAILED
            result.total_time_secs = time.time() - t0
            print(f"[Orchestrator] ✗ Pipeline failed: {e}")
            traceback.print_exc()
            return result
