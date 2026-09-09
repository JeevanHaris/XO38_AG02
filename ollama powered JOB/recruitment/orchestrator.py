"""
RecruitScreen / ARIA Core — Recruitment Orchestrator
────────────────────────────────────────────────────
Agentic orchestrator coordinating the lean, two-model candidate screening pipeline.

Pipeline:
  1.  Process Documents (PyMuPDF / docx clean text extraction)
  2.  Analyze JD (Llama 3.2 + Pydantic validation)
  2b. [NEW] Detect Requirement Conflicts (Llama 3.2 -> Groq if ambiguous)
  3.  Analyze Resumes (Llama 3.2 + Pydantic validation)
  4.  Extract Skill Claims (Llama 3.2)
  5.  Retrieve Evidence (Fast section-aware extraction)
  6.  Verify Evidence (🟢 Strongly Supported, 🟡 Partially Supported, 🔴 Unsupported, ⚪ Not Mentioned)
  5b. [NEW] GitHub Evidence (GitHubMCPClient + GitHubEvidenceVerifier) — OPTIONAL
  7.  Semantic Skill Matching (Taxonomy + normalized matching)
  8.  Calculate Deterministic Scores (Python: 40% Required, 25% Experience, 20% Evidence, 10% Preferred, 5% Education)
  9.  [NEW] Pool Coverage Analysis (Python -- intersection check)
  10. [NEW] Agentic Fork:
        intersection > 0 -> Standard Ranking (Groq trade-off, top 2)
        intersection == 0 -> Trade-Off Shortlist Builder (Groq narratives)
  11. Identify Skill Gaps (Python pool stats + Groq advisory summary)
  12. Persist to SQLite Recruitment Memory
"""

import time
import uuid
from typing import Callable, Optional

from .models import (
    ScreeningResult, PipelineStage, CandidateProfile,
)
from .doc_processor                        import DocumentProcessor
from .agents.jd_analyzer                   import JDAnalyzerAgent
from .agents.resume_analyzer               import ResumeAnalyzerAgent
from .agents.claim_extractor               import ClaimExtractorAgent
from .agents.evidence_retrieval            import EvidenceRetrievalAgent
from .agents.evidence_verifier             import EvidenceVerifierAgent
from .agents.skill_matcher                 import SemanticSkillMatcher
from .agents.requirement_conflict_analyzer import RequirementConflictAnalyzer
from .agents.github_evidence_verifier      import GitHubEvidenceVerifier
from .github_mcp                           import GitHubMCPClient
from .ranking.scorer                       import CandidateScorer
from .ranking.comparator                   import CandidateComparator
from .ranking.gap_analyzer                 import RequirementGapAnalyzer
from .ranking.pool_coverage_analyzer       import PoolCoverageAnalyzer
from .ranking.tradeoff_shortlist_builder   import TradeOffShortlistBuilder
from .memory_store                         import RecruitmentMemory


class RecruitmentOrchestrator:
    """
    Coordinates the agentic talent screening pipeline.
    Progress is reported via an optional callback so the server streams updates.
    """

    def __init__(self, gateway, router, db_path: str = None, github_token: str = ""):
        self.gateway       = gateway
        self.router        = router
        self.github_token  = github_token or ""

        # Initialize all agents & services
        self.doc_processor         = DocumentProcessor()
        self.jd_analyzer           = JDAnalyzerAgent(gateway, router)
        self.resume_analyzer       = ResumeAnalyzerAgent(gateway, router)
        self.claim_extractor       = ClaimExtractorAgent(gateway, router)
        self.evidence_retrieval    = EvidenceRetrievalAgent()
        self.evidence_verifier     = EvidenceVerifierAgent(gateway, router)
        self.skill_matcher         = SemanticSkillMatcher(gateway, router)
        self.conflict_analyzer     = RequirementConflictAnalyzer(gateway, router)
        self.github_verifier       = GitHubEvidenceVerifier(gateway, router)  # [NEW]
        self.scorer                = CandidateScorer()
        self.comparator            = CandidateComparator(gateway, router)
        self.gap_analyzer          = RequirementGapAnalyzer(gateway, router)
        self.pool_coverage         = PoolCoverageAnalyzer()
        self.tradeoff_builder      = TradeOffShortlistBuilder(gateway, router)
        self.memory                = RecruitmentMemory(db_path=db_path)

    def run_screening(
        self,
        jd_file:      tuple[str, bytes],             # (filename, bytes)
        resume_files: list[tuple[str, bytes]],        # [(filename, bytes), ...]
        session_id:   str = None,
        progress_cb:  Callable[[ScreeningResult], None] = None,
        github_urls:  dict[str, str] = None,          # [NEW] {filename: github_url}
        github_token: str = None,                     # [NEW] override token per-run
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

            # Deduplicate resumes by filename to prevent duplicate candidate evaluations
            seen_filenames = set()
            deduped_resumes = []
            for item in resume_files:
                fname = item[0]
                if fname not in seen_filenames:
                    seen_filenames.add(fname)
                    deduped_resumes.append(item)
                else:
                    print(f"[Orchestrator] Skipped duplicate resume file: {fname}")
            resume_files = deduped_resumes

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
                update(PipelineStage.ANALYZING_JD, 18,
                       "⚠ No required skills explicitly extracted. Falling back to key skills.")
            else:
                update(PipelineStage.ANALYZING_JD, 18,
                       f"JD analyzed: {jd_analysis.role_title} — "
                       f"{len(jd_analysis.required_skills)} required, "
                       f"{len(jd_analysis.preferred_skills)} preferred skills")

            # ── Stage 2b: Detect Requirement Conflicts [NEW] ──────────
            update(PipelineStage.FEASIBILITY_ANALYSIS, 20,
                   "Analyzing JD for internal requirement conflicts...")
            feasibility_report = self.conflict_analyzer.analyze(jd_analysis)
            result.feasibility_report = feasibility_report
            sev = feasibility_report.overall_severity.value
            n_conflicts = len(feasibility_report.conflicts)
            if sev == "NONE":
                update(PipelineStage.FEASIBILITY_ANALYSIS, 22,
                       "Feasibility check passed: Requirements appear consistent")
            else:
                icon = feasibility_report.severity_icon
                update(PipelineStage.FEASIBILITY_ANALYSIS, 22,
                       f"{icon} Requirement conflict detected [{sev}]: "
                       f"{n_conflicts} conflict(s) found")

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

            # ── Attach GitHub URLs to profiles ────────────────────────
            if github_urls:
                for profile in profiles:
                    url = github_urls.get(profile.filename, "")
                    if not url:
                        # Also try without extension match
                        for fname, gurl in github_urls.items():
                            if fname in profile.filename or profile.filename in fname:
                                url = gurl
                                break
                    if url:
                        profile.github_url = url.strip()

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

            # ── Stage 5b: GitHub Evidence Collection [NEW] ─────────────
            effective_token = github_token or self.github_token
            profiles_with_github = [p for p in profiles if p.github_url]

            if profiles_with_github and effective_token:
                update(PipelineStage.GITHUB_EVIDENCE, 77,
                       f"Fetching GitHub evidence for {len(profiles_with_github)} "
                       f"candidate(s) with GitHub profiles...")

                gh_client = GitHubMCPClient(token=effective_token)

                for i, profile in enumerate(profiles_with_github):
                    pct = 77 + (i / len(profiles_with_github)) * 2
                    update(PipelineStage.GITHUB_EVIDENCE, pct,
                           f"GitHub: fetching evidence for {profile.name} "
                           f"(@{profile.github_url.split('/')[-1]})...")

                    # Collect GitHub evidence
                    gh_evidence = gh_client.collect_evidence(
                        github_url    = profile.github_url,
                        target_skills = jd_analysis.required_skills,
                    )

                    if gh_evidence.fetch_error:
                        update(PipelineStage.GITHUB_EVIDENCE, pct,
                               f"⚠ GitHub fetch issue for {profile.name}: "
                               f"{gh_evidence.fetch_error}")
                        continue

                    # Verify skills against GitHub evidence
                    claims = all_claims.get(profile.candidate_id, [])
                    if not claims:
                        continue

                    gh_results = self.github_verifier.verify_all(
                        claims          = claims,
                        github_evidence = gh_evidence,
                    )

                    # Merge GitHub results into existing VerificationResults
                    existing_verifs = all_verifications.get(profile.candidate_id, [])
                    for verif in existing_verifs:
                        skill = verif.jd_skill
                        if skill in gh_results:
                            verif.github_result = gh_results[skill]

                    n_supported = sum(
                        1 for r in gh_results.values()
                        if r.status.value == "SUPPORTED"
                    )
                    n_partial = sum(
                        1 for r in gh_results.values()
                        if r.status.value == "PARTIAL"
                    )
                    update(PipelineStage.GITHUB_EVIDENCE, pct,
                           f"GitHub evidence for {profile.name}: "
                           f"🟢 {n_supported} corroborated, "
                           f"🟡 {n_partial} partial, "
                           f"⚪ {len(gh_results) - n_supported - n_partial} unverified")

            elif profiles_with_github and not effective_token:
                update(PipelineStage.GITHUB_EVIDENCE, 77,
                       f"⚪ {len(profiles_with_github)} candidate(s) have GitHub URLs "
                       f"but no GitHub token configured. Skipping GitHub evidence.")
            else:
                update(PipelineStage.GITHUB_EVIDENCE, 77,
                       "No GitHub URLs provided — skipping GitHub evidence stage")

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

            # -- Stage 9: Pool Coverage Analysis (Python) [NEW] -------------
            update(PipelineStage.POOL_COVERAGE, 91,
                   f"Calculating requirement coverage across {len(all_scores)} candidates...")
            coverage = self.pool_coverage.analyze(jd_analysis, all_scores)
            ic       = coverage.intersection_count
            total_c  = coverage.total_candidates
            if ic == 0:
                update(PipelineStage.POOL_COVERAGE, 92,
                       f"No candidate satisfies all requirements (0/{total_c}). "
                       f"Building compromise shortlist...")
            else:
                update(PipelineStage.POOL_COVERAGE, 92,
                       f"{ic}/{total_c} candidates satisfy all requirements. "
                       f"Proceeding with standard ranking.")

            # -- Stage 10: Agentic Fork [NEW] --------------------------------
            if ic == 0:
                # No perfect match -- build trade-off shortlist
                update(PipelineStage.TRADEOFF_ANALYSIS, 93,
                       "Building trade-off shortlist with Groq narratives...")
                tradeoff_shortlist        = self.tradeoff_builder.build(
                    all_scores, jd_analysis, coverage
                )
                result.tradeoff_shortlist = tradeoff_shortlist

                # Still compute standard ranking for score reference
                ranked_list        = self.comparator.rank(all_scores, jd_analysis)
                result.ranked_list = ranked_list
                top_name = (ranked_list.candidates[0].score.candidate_name
                            if ranked_list.candidates else "N/A")
                update(PipelineStage.TRADEOFF_ANALYSIS, 95,
                       f"Trade-off shortlist ready. Closest match: {top_name}")
            else:
                # Perfect matches exist -- standard ranking path
                update(PipelineStage.RANKING, 93,
                       "Ranking candidates & generating Groq trade-off analysis...")
                ranked_list        = self.comparator.rank(all_scores, jd_analysis)
                result.ranked_list = ranked_list

                # Still build shortlist so frontend always has tradeoff data
                tradeoff_shortlist        = self.tradeoff_builder.build(
                    all_scores, jd_analysis, coverage
                )
                result.tradeoff_shortlist = tradeoff_shortlist

                top_name = (ranked_list.candidates[0].score.candidate_name
                            if ranked_list.candidates else "N/A")
                update(PipelineStage.RANKING, 95,
                       f"Ranking complete. Top candidate: {top_name}")

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
