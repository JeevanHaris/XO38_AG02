"""
RecruitScreen v1.0 — Data Models
──────────────────────────────────
All dataclasses used across the recruitment pipeline.

Hierarchy:
  JDAnalysis                ← JD Analyzer Agent output
  CandidateProfile          ← Resume Analyzer Agent output
  Claim                     ← Claim Extractor Agent output
  Evidence                  ← Evidence Retrieval Agent output
  VerificationResult        ← Evidence Verifier Agent output
  GitHubRepo                ← GitHub MCP snapshot for one repository
  GitHubEvidence            ← All collected GitHub repos for one candidate
  GitHubVerificationResult  ← Per-skill GitHub cross-validation result
  SkillMatch                ← Semantic Skill Matcher output
  CandidateScore            ← Scorer output
  RankedList                ← Comparator output
  GapReport                 ← Gap Analyzer output
  ScreeningResult           ← Full pipeline output
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────

class VerificationStatus(str, Enum):
    STRONGLY_SUPPORTED  = "STRONGLY_SUPPORTED"    # 🟢
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"   # 🟡
    UNSUPPORTED         = "UNSUPPORTED"           # 🔴
    NOT_MENTIONED       = "NOT_MENTIONED"         # ⚪

class GapRiskLevel(str, Enum):
    ADEQUATE  = "ADEQUATE"   # >= 70% candidates have the skill
    MODERATE  = "MODERATE"   # 40-70%
    HIGH_RISK = "HIGH_RISK"  # < 40%

class ConflictSeverity(str, Enum):
    NONE     = "NONE"      # Requirements are consistent
    MODERATE = "MODERATE"  # Restrictive combination — significantly shrinks pool
    HIGH     = "HIGH"      # Logically contradictory (e.g. 10yr exp + Junior)

class PipelineStage(str, Enum):
    IDLE                 = "idle"
    PROCESSING_DOCS      = "processing_documents"
    ANALYZING_JD         = "analyzing_jd"
    FEASIBILITY_ANALYSIS = "feasibility_analysis"
    ANALYZING_RESUMES    = "analyzing_resumes"
    EXTRACTING_CLAIMS    = "extracting_claims"
    RETRIEVING_EVIDENCE  = "retrieving_evidence"
    VERIFYING_EVIDENCE   = "verifying_evidence"
    GITHUB_EVIDENCE      = "github_evidence"       # [NEW] Stage 5b
    MATCHING_SKILLS      = "matching_skills"
    SCORING              = "scoring"
    POOL_COVERAGE        = "pool_coverage"
    RANKING              = "ranking"
    TRADEOFF_ANALYSIS    = "tradeoff_analysis"
    GAP_ANALYSIS         = "gap_analysis"
    COMPLETE             = "complete"
    FAILED               = "failed"


# ─── JD Analysis ──────────────────────────────────────────────────────

@dataclass
class JDAnalysis:
    """Structured output from the JD Analyzer Agent."""
    role_title:        str               = ""
    seniority_level:   str               = ""
    required_skills:   list[str]         = field(default_factory=list)
    preferred_skills:  list[str]         = field(default_factory=list)
    experience_years:  str               = ""      # e.g. "3-5 years"
    education:         list[str]         = field(default_factory=list)
    certifications:    list[str]         = field(default_factory=list)
    responsibilities:  list[str]         = field(default_factory=list)
    raw_text:          str               = ""      # original JD text
    filename:          str               = ""

    def to_dict(self) -> dict:
        return {
            "role_title":       self.role_title,
            "seniority_level":  self.seniority_level,
            "required_skills":  self.required_skills,
            "preferred_skills": self.preferred_skills,
            "experience_years": self.experience_years,
            "education":        self.education,
            "certifications":   self.certifications,
            "responsibilities": self.responsibilities,
            "filename":         self.filename,
        }


# ─── Resume / Candidate Profile ───────────────────────────────────────

@dataclass
class ExperienceEntry:
    title:        str = ""
    company:      str = ""
    duration:     str = ""
    description:  str = ""

    def to_dict(self) -> dict:
        return {
            "title":       self.title,
            "company":     self.company,
            "duration":    self.duration,
            "description": self.description,
        }


@dataclass
class CandidateProfile:
    """Structured output from the Resume Analyzer Agent."""
    candidate_id:       str                    = field(default_factory=lambda: "")
    name:               str                    = ""
    email:              str                    = ""
    phone:              str                    = ""
    skills:             list[str]              = field(default_factory=list)
    experience_entries: list[ExperienceEntry]  = field(default_factory=list)
    total_experience_years: float              = 0.0
    projects:           list[str]              = field(default_factory=list)
    education:          list[str]              = field(default_factory=list)
    certifications:     list[str]              = field(default_factory=list)
    raw_claims:         list[str]              = field(default_factory=list)  # unverified claims
    raw_text:           str                    = ""
    filename:           str                    = ""
    github_url:         str                    = ""   # [NEW] candidate-provided GitHub profile URL

    def to_dict(self) -> dict:
        return {
            "candidate_id":          self.candidate_id,
            "name":                  self.name,
            "email":                 self.email,
            "phone":                 self.phone,
            "skills":                self.skills,
            "experience_entries":    [e.to_dict() for e in self.experience_entries],
            "total_experience_years": self.total_experience_years,
            "projects":              self.projects,
            "education":             self.education,
            "certifications":        self.certifications,
            "filename":              self.filename,
            "github_url":            self.github_url,
        }


# ─── Claims & Evidence ────────────────────────────────────────────────

@dataclass
class Claim:
    """A single verifiable claim about a candidate skill/experience."""
    skill:           str    = ""
    statement:       str    = ""   # e.g. "Built 3 FastAPI services"
    source_section:  str    = ""   # which resume section this came from
    jd_skill:        str    = ""   # which JD requirement this maps to
    candidate_id:    str    = ""

    def to_dict(self) -> dict:
        return {
            "skill":          self.skill,
            "statement":      self.statement,
            "source_section": self.source_section,
            "jd_skill":       self.jd_skill,
            "candidate_id":   self.candidate_id,
        }


@dataclass
class Evidence:
    """A resume passage that may support a claim."""
    chunk_text:       str    = ""
    similarity_score: float  = 0.0
    source_section:   str    = ""

    def to_dict(self) -> dict:
        return {
            "chunk_text":       self.chunk_text,
            "similarity_score": round(self.similarity_score, 4),
            "source_section":   self.source_section,
        }


@dataclass
class GitHubRepo:
    """Snapshot of a single GitHub repository."""
    name:           str        = ""
    description:    str        = ""
    language:       str        = ""          # primary language
    languages:      dict       = field(default_factory=dict)  # {lang: bytes}
    readme_excerpt: str        = ""          # first 800 chars of README
    topics:         list[str]  = field(default_factory=list)
    pushed_at:      str        = ""

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "description":    self.description,
            "language":       self.language,
            "languages":      self.languages,
            "readme_excerpt": self.readme_excerpt,
            "topics":         self.topics,
            "pushed_at":      self.pushed_at,
        }


@dataclass
class GitHubEvidence:
    """All retrieved GitHub repositories for a single candidate."""
    github_username: str             = ""
    github_url:      str             = ""
    repos:           list[GitHubRepo] = field(default_factory=list)
    fetch_error:     str             = ""   # empty if successful
    total_repos:     int             = 0

    def to_dict(self) -> dict:
        return {
            "github_username": self.github_username,
            "github_url":      self.github_url,
            "repos":           [r.to_dict() for r in self.repos],
            "fetch_error":     self.fetch_error,
            "total_repos":     self.total_repos,
        }


class GitHubEvidenceStatus(str, Enum):
    SUPPORTED  = "SUPPORTED"    # Clear repo evidence found
    PARTIAL    = "PARTIAL"      # Indirect/weak evidence
    UNVERIFIED = "UNVERIFIED"   # No GitHub evidence — NOT a negative judgment


@dataclass
class GitHubVerificationResult:
    """Per-skill GitHub cross-validation result."""
    skill:        str                  = ""
    status:       GitHubEvidenceStatus = GitHubEvidenceStatus.UNVERIFIED
    confidence:   str                  = "LOW"    # HIGH | MEDIUM | LOW
    evidence_repos: list[str]          = field(default_factory=list)  # repo names
    reasoning:    str                  = ""

    @property
    def status_icon(self) -> str:
        return {
            GitHubEvidenceStatus.SUPPORTED:  "🟢",
            GitHubEvidenceStatus.PARTIAL:    "🟡",
            GitHubEvidenceStatus.UNVERIFIED: "⚪",
        }.get(self.status, "⚪")

    @property
    def status_label(self) -> str:
        """Human-readable label that avoids false negatives."""
        return {
            GitHubEvidenceStatus.SUPPORTED:  "Externally corroborated",
            GitHubEvidenceStatus.PARTIAL:    "Partial GitHub evidence",
            GitHubEvidenceStatus.UNVERIFIED: "Not externally corroborated",
        }.get(self.status, "Not externally corroborated")

    def to_dict(self) -> dict:
        return {
            "skill":          self.skill,
            "status":         self.status.value,
            "status_icon":    self.status_icon,
            "status_label":   self.status_label,
            "confidence":     self.confidence,
            "evidence_repos": self.evidence_repos,
            "reasoning":      self.reasoning,
        }


@dataclass
class VerificationResult:
    """Verification of a single claim against resume + (optionally) GitHub evidence."""
    claim:            Claim                             = field(default_factory=Claim)
    evidence:         list[Evidence]                   = field(default_factory=list)
    status:           VerificationStatus               = VerificationStatus.NOT_MENTIONED
    explanation:      str                              = ""
    confidence_score: float                            = 0.0   # 0.0–1.0
    jd_skill:         str                              = ""
    github_result:    Optional["GitHubVerificationResult"] = None  # [NEW] Stage 5b

    @property
    def status_icon(self) -> str:
        icons = {
            VerificationStatus.STRONGLY_SUPPORTED:  "🟢",
            VerificationStatus.PARTIALLY_SUPPORTED: "🟡",
            VerificationStatus.UNSUPPORTED:         "🔴",
            VerificationStatus.NOT_MENTIONED:       "⚪",
        }
        return icons.get(self.status, "⚪")

    def to_dict(self) -> dict:
        return {
            "claim":            self.claim.to_dict(),
            "evidence":         [e.to_dict() for e in self.evidence],
            "status":           self.status.value,
            "status_icon":      self.status_icon,
            "explanation":      self.explanation,
            "confidence_score": round(self.confidence_score, 3),
            "jd_skill":         self.jd_skill,
            "github_result":    self.github_result.to_dict() if self.github_result else None,
        }


# ─── Semantic Skill Matching ──────────────────────────────────────────

@dataclass
class SkillMatch:
    """Result of semantic matching between a JD skill and candidate skills."""
    jd_skill:         str   = ""
    candidate_skill:  str   = ""   # best matching candidate skill
    similarity:       float = 0.0  # cosine similarity 0–1
    matched:          bool  = False
    match_type:       str   = ""   # "exact" | "semantic" | "none"

    def to_dict(self) -> dict:
        return {
            "jd_skill":        self.jd_skill,
            "candidate_skill": self.candidate_skill,
            "similarity":      round(self.similarity, 3),
            "matched":         self.matched,
            "match_type":      self.match_type,
        }


# ─── Scoring ──────────────────────────────────────────────────────────

@dataclass
class ComponentScore:
    """One component of the overall candidate score."""
    name:        str   = ""
    score:       float = 0.0    # 0–100
    weight:      float = 0.0    # fraction
    weighted:    float = 0.0    # score * weight
    detail:      str   = ""

    def to_dict(self) -> dict:
        return {
            "name":     self.name,
            "score":    round(self.score, 1),
            "weight":   self.weight,
            "weighted": round(self.weighted, 2),
            "detail":   self.detail,
        }


@dataclass
class CandidateScore:
    """Full scoring result for one candidate."""
    candidate_id:       str                       = ""
    candidate_name:     str                       = ""
    total_score:        float                     = 0.0     # 0–100
    component_scores:   list[ComponentScore]      = field(default_factory=list)
    skill_breakdown:    list[VerificationResult]  = field(default_factory=list)
    skill_matches:      list[SkillMatch]          = field(default_factory=list)
    profile:            Optional[CandidateProfile] = None

    @property
    def evidence_fit_pct(self) -> float:
        """Percentage of required skills with at least partial support."""
        if not self.skill_breakdown:
            return 0.0
        supported = sum(
            1 for v in self.skill_breakdown
            if v.status in (VerificationStatus.STRONGLY_SUPPORTED,
                            VerificationStatus.PARTIALLY_SUPPORTED)
        )
        return round(supported / len(self.skill_breakdown) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "candidate_id":     self.candidate_id,
            "candidate_name":   self.candidate_name,
            "total_score":      round(self.total_score, 1),
            "evidence_fit_pct": self.evidence_fit_pct,
            "component_scores": [c.to_dict() for c in self.component_scores],
            "skill_breakdown":  [v.to_dict() for v in self.skill_breakdown],
            "skill_matches":    [m.to_dict() for m in self.skill_matches],
            "profile":          self.profile.to_dict() if self.profile else None,
        }


# ─── Ranking ──────────────────────────────────────────────────────────

@dataclass
class RankedCandidate:
    rank:           int           = 0
    score:          CandidateScore = field(default_factory=CandidateScore)
    tradeoff_note:  str           = ""   # LLM-generated trade-off summary

    def to_dict(self) -> dict:
        return {
            "rank":          self.rank,
            "score":         self.score.to_dict(),
            "tradeoff_note": self.tradeoff_note,
        }


@dataclass
class RankedList:
    """Final sorted list of candidates."""
    candidates:    list[RankedCandidate] = field(default_factory=list)
    jd_role:       str                   = ""
    total_analyzed: int                  = 0

    def to_dict(self) -> dict:
        return {
            "candidates":     [c.to_dict() for c in self.candidates],
            "jd_role":        self.jd_role,
            "total_analyzed": self.total_analyzed,
        }


# ─── Gap Analysis ─────────────────────────────────────────────────────

@dataclass
class SkillGap:
    """Pool-level coverage for a single required skill."""
    skill:           str          = ""
    count_with_skill: int         = 0
    total_candidates: int         = 0
    percentage:       float       = 0.0
    risk_level:       GapRiskLevel = GapRiskLevel.ADEQUATE

    def to_dict(self) -> dict:
        return {
            "skill":             self.skill,
            "count_with_skill":  self.count_with_skill,
            "total_candidates":  self.total_candidates,
            "percentage":        round(self.percentage, 1),
            "risk_level":        self.risk_level.value,
        }


@dataclass
class GapReport:
    """Pool-level skill gap analysis across all candidates."""
    skill_gaps:       list[SkillGap] = field(default_factory=list)
    total_candidates: int            = 0
    high_risk_skills: list[str]      = field(default_factory=list)
    summary:          str            = ""

    def to_dict(self) -> dict:
        return {
            "skill_gaps":       [g.to_dict() for g in self.skill_gaps],
            "total_candidates": self.total_candidates,
            "high_risk_skills": self.high_risk_skills,
            "summary":          self.summary,
        }


# ─── Requirement Feasibility Engine ─────────────────────────────────

@dataclass
class RequirementConflict:
    """A single detected conflict within the JD requirements."""
    requirement_a:  str               = ""    # First conflicting requirement
    requirement_b:  str               = ""    # Second (or compound) requirement
    severity:       ConflictSeverity  = ConflictSeverity.NONE
    explanation:    str               = ""    # Human-readable reason

    def to_dict(self) -> dict:
        return {
            "requirement_a": self.requirement_a,
            "requirement_b": self.requirement_b,
            "severity":      self.severity.value,
            "explanation":   self.explanation,
        }


@dataclass
class FeasibilityReport:
    """Self-conflict analysis of a job requisition."""
    conflicts:           list[RequirementConflict] = field(default_factory=list)
    overall_severity:    ConflictSeverity          = ConflictSeverity.NONE
    recruiter_advisory:  str                       = ""
    analyzed_at_stage:   str                       = "post_jd_analysis"

    @property
    def severity_icon(self) -> str:
        return {"NONE": "✅", "MODERATE": "⚠️", "HIGH": "🚨"}.get(
            self.overall_severity.value, "⚠️"
        )

    def to_dict(self) -> dict:
        return {
            "conflicts":          [c.to_dict() for c in self.conflicts],
            "overall_severity":   self.overall_severity.value,
            "severity_icon":      self.severity_icon,
            "recruiter_advisory": self.recruiter_advisory,
        }


@dataclass
class CoverageEntry:
    """Pool coverage for a single requirement."""
    requirement:   str   = ""
    count:         int   = 0    # Candidates meeting this requirement
    total:         int   = 0    # Total candidates evaluated
    percentage:    float = 0.0
    bar:           str   = ""   # ASCII-art progress bar for display

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "count":       self.count,
            "total":       self.total,
            "percentage":  round(self.percentage, 1),
            "bar":         self.bar,
        }


@dataclass
class RequirementCoverage:
    """Pure-Python pool coverage analysis across all JD requirements."""
    entries:            list[CoverageEntry]  = field(default_factory=list)
    intersection_count: int                  = 0   # Candidates satisfying ALL requirements
    intersection_pct:   float               = 0.0
    total_candidates:   int                  = 0
    has_perfect_match:  bool                 = False

    def to_dict(self) -> dict:
        return {
            "entries":            [e.to_dict() for e in self.entries],
            "intersection_count": self.intersection_count,
            "intersection_pct":   round(self.intersection_pct, 1),
            "total_candidates":   self.total_candidates,
            "has_perfect_match":  self.has_perfect_match,
        }


@dataclass
class TradeOffCandidate:
    """A candidate in the compromise shortlist, annotated with met/unmet requirements."""
    rank:             int        = 0
    candidate_id:     str        = ""
    candidate_name:   str        = ""
    total_score:      float      = 0.0
    met:              list[str]  = field(default_factory=list)   # ✅ requirements met
    partial:          list[str]  = field(default_factory=list)   # 🟡 partially met
    unmet:            list[str]  = field(default_factory=list)   # ❌ not met
    unmet_count:      int        = 0
    compromise_score: float      = 0.0  # 0.0 = perfect match, 1.0 = all unmet
    tradeoff_note:    str        = ""

    def to_dict(self) -> dict:
        return {
            "rank":             self.rank,
            "candidate_id":     self.candidate_id,
            "candidate_name":   self.candidate_name,
            "total_score":      round(self.total_score, 1),
            "met":              self.met,
            "partial":          self.partial,
            "unmet":            self.unmet,
            "unmet_count":      self.unmet_count,
            "compromise_score": round(self.compromise_score, 3),
            "tradeoff_note":    self.tradeoff_note,
        }


@dataclass
class FeasibilityShortlist:
    """Compromise-aware shortlist — the primary output when intersection_count == 0."""
    has_perfect_match:     bool                  = False
    perfect_matches:       list[TradeOffCandidate] = field(default_factory=list)
    compromise_candidates: list[TradeOffCandidate] = field(default_factory=list)
    intersection_count:    int                   = 0
    total_candidates:      int                   = 0
    coverage:              Optional[RequirementCoverage] = None

    def to_dict(self) -> dict:
        return {
            "has_perfect_match":     self.has_perfect_match,
            "perfect_matches":       [c.to_dict() for c in self.perfect_matches],
            "compromise_candidates": [c.to_dict() for c in self.compromise_candidates],
            "intersection_count":    self.intersection_count,
            "total_candidates":      self.total_candidates,
            "coverage":              self.coverage.to_dict() if self.coverage else None,
        }


# ─── Full Screening Result ────────────────────────────────────────────

@dataclass
class ScreeningResult:
    """Complete output of the RecruitmentOrchestrator pipeline."""
    session_id:          str                            = ""
    jd_analysis:         Optional[JDAnalysis]           = None
    candidates:          list[CandidateProfile]         = field(default_factory=list)
    ranked_list:         Optional[RankedList]           = None
    gap_report:          Optional[GapReport]            = None
    feasibility_report:  Optional[FeasibilityReport]    = None
    tradeoff_shortlist:  Optional[FeasibilityShortlist] = None
    pipeline_stage:      PipelineStage                  = PipelineStage.IDLE
    progress_pct:        float                          = 0.0
    progress_log:        list[str]                      = field(default_factory=list)
    total_time_secs:     float                          = 0.0
    error:               Optional[str]                  = None

    def to_dict(self) -> dict:
        return {
            "session_id":         self.session_id,
            "jd_analysis":        self.jd_analysis.to_dict() if self.jd_analysis else None,
            "ranked_list":        self.ranked_list.to_dict() if self.ranked_list else None,
            "gap_report":         self.gap_report.to_dict() if self.gap_report else None,
            "feasibility_report": self.feasibility_report.to_dict() if self.feasibility_report else None,
            "tradeoff_shortlist": self.tradeoff_shortlist.to_dict() if self.tradeoff_shortlist else None,
            "pipeline_stage":     self.pipeline_stage.value,
            "progress_pct":       round(self.progress_pct, 1),
            "progress_log":       self.progress_log,
            "total_time_secs":    round(self.total_time_secs, 2),
            "error":              self.error,
            "candidate_count":    len(self.candidates),
        }
