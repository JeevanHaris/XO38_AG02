"""
RecruitScreen / ARIA Core — Recruitment Memory Store
────────────────────────────────────────────────────
SQLite-backed persistent recruitment memory for jobs, candidates,
verifications, deterministic rankings, and historical analyses.

Structure:
  Recruitment Memory
  ├── Job (Requirements, Preferences)
  ├── Candidates (Skills, Claims, Evidence, Verification)
  ├── Rankings (Scores, Component Breakdown, Trade-offs)
  └── Previous Analysis (Skill Gaps, Talent Pool Insights)
"""

import os
import json
import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime

from .models import ScreeningResult, CandidateScore, VerificationStatus


class RecruitmentMemory:
    """Persistent SQLite memory store for recruitment data and recruiter chat grounding."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            base_dir = os.path.join(os.path.expanduser("~"), ".recruitscreen")
            os.makedirs(base_dir, exist_ok=True)
            db_path = os.path.join(base_dir, "recruitment.db")
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # 1. Jobs table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                session_id TEXT PRIMARY KEY,
                role_title TEXT,
                seniority_level TEXT,
                required_skills TEXT,
                preferred_skills TEXT,
                experience_years TEXT,
                education TEXT,
                certifications TEXT,
                responsibilities TEXT,
                raw_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 2. Candidates table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT,
                session_id TEXT,
                name TEXT,
                email TEXT,
                phone TEXT,
                skills TEXT,
                experience_entries TEXT,
                total_experience_years REAL,
                projects TEXT,
                education TEXT,
                certifications TEXT,
                raw_claims TEXT,
                raw_text TEXT,
                filename TEXT,
                github_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (candidate_id, session_id)
            )
            """)

            # 3. Evidence Verifications table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                candidate_id TEXT,
                jd_skill TEXT,
                claim_statement TEXT,
                status TEXT,
                confidence_score REAL,
                explanation TEXT,
                evidence TEXT,
                github_status TEXT DEFAULT '',
                github_confidence TEXT DEFAULT '',
                github_evidence TEXT DEFAULT '[]',
                github_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 4. Rankings table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS rankings (
                session_id TEXT,
                candidate_id TEXT,
                rank INTEGER,
                total_score REAL,
                component_scores TEXT,
                tradeoff_note TEXT,
                PRIMARY KEY (session_id, candidate_id)
            )
            """)

            # 5. Analyses (Gaps & Summary)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                session_id TEXT PRIMARY KEY,
                gap_report TEXT,
                summary TEXT,
                total_candidates INTEGER,
                feasibility_report TEXT,
                tradeoff_shortlist TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Ensure columns exist if table was created in an earlier version
            _version_cols = [
                ("analyses",      "feasibility_report",  "TEXT"),
                ("analyses",      "tradeoff_shortlist",   "TEXT"),
                ("candidates",    "github_url",           "TEXT DEFAULT ''"),
                ("verifications", "github_status",        "TEXT DEFAULT ''"),
                ("verifications", "github_confidence",    "TEXT DEFAULT ''"),
                ("verifications", "github_evidence",      "TEXT DEFAULT '[]'"),
                ("verifications", "github_url",           "TEXT DEFAULT ''"),
            ]
            for table, col, col_def in _version_cols:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                except Exception:
                    pass

            # 6. Chat History
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                model TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.commit()

    def save_screening_result(self, result: ScreeningResult):
        """Persists the complete screening result into SQLite."""
        session_id = result.session_id
        if not session_id:
            return

        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Clear any previous candidate/ranking/verification data for this session to prevent duplicates
            cursor.execute("DELETE FROM verifications WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM rankings WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM candidates WHERE session_id = ?", (session_id,))

            # Save Job
            if result.jd_analysis:
                jd = result.jd_analysis
                cursor.execute("""
                INSERT OR REPLACE INTO jobs 
                (session_id, role_title, seniority_level, required_skills, preferred_skills, experience_years, education, certifications, responsibilities, raw_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    jd.role_title,
                    jd.seniority_level,
                    json.dumps(jd.required_skills),
                    json.dumps(jd.preferred_skills),
                    jd.experience_years,
                    json.dumps(jd.education),
                    json.dumps(jd.certifications),
                    json.dumps(jd.responsibilities),
                    jd.raw_text,
                ))

            # Save Candidates
            for cand in result.candidates:
                cursor.execute("""
                INSERT OR REPLACE INTO candidates
                (candidate_id, session_id, name, email, phone, skills, experience_entries,
                 total_experience_years, projects, education, certifications, raw_claims,
                 raw_text, filename, github_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cand.candidate_id,
                    session_id,
                    cand.name,
                    cand.email,
                    cand.phone,
                    json.dumps(cand.skills),
                    json.dumps([e.to_dict() for e in cand.experience_entries]),
                    cand.total_experience_years,
                    json.dumps(cand.projects),
                    json.dumps(cand.education),
                    json.dumps(cand.certifications),
                    json.dumps(cand.raw_claims),
                    cand.raw_text,
                    cand.filename,
                    cand.github_url,
                ))

            # Save Rankings & Verifications
            if result.ranked_list:
                for ranked in result.ranked_list.candidates:
                    s = ranked.score
                    cursor.execute("""
                    INSERT OR REPLACE INTO rankings
                    (session_id, candidate_id, rank, total_score, component_scores, tradeoff_note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        session_id,
                        s.candidate_id,
                        ranked.rank,
                        s.total_score,
                        json.dumps([c.to_dict() for c in s.component_scores]),
                        ranked.tradeoff_note,
                    ))

                    # Save each verified skill breakdown
                    for v in s.skill_breakdown:
                        gh   = v.github_result
                        cursor.execute("""
                        INSERT INTO verifications
                        (session_id, candidate_id, jd_skill, claim_statement, status,
                         confidence_score, explanation, evidence,
                         github_status, github_confidence, github_evidence, github_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            session_id,
                            s.candidate_id,
                            v.jd_skill,
                            v.claim.statement if v.claim else "",
                            v.status.value,
                            v.confidence_score,
                            v.explanation,
                            json.dumps([e.to_dict() for e in v.evidence]),
                            gh.status.value      if gh else "",
                            gh.confidence        if gh else "",
                            json.dumps(gh.evidence_repos if gh else []),
                            s.profile.github_url if s.profile else "",
                        ))

            # Save Analyses (Gaps & Feasibility)
            feasibility_json = json.dumps(result.feasibility_report.to_dict()) if result.feasibility_report else None
            tradeoff_json = json.dumps(result.tradeoff_shortlist.to_dict()) if result.tradeoff_shortlist else None
            gap_json = json.dumps(result.gap_report.to_dict()) if result.gap_report else None
            summary = result.gap_report.summary if result.gap_report else ""
            total_cand = result.gap_report.total_candidates if result.gap_report else len(result.candidates)

            if gap_json or feasibility_json or tradeoff_json:
                cursor.execute("""
                INSERT OR REPLACE INTO analyses
                (session_id, gap_report, summary, total_candidates, feasibility_report, tradeoff_shortlist)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    gap_json,
                    summary,
                    total_cand,
                    feasibility_json,
                    tradeoff_json,
                ))

            conn.commit()
            print(f"[RecruitmentMemory] Saved session {session_id} to SQLite ({len(result.candidates)} candidates).")

    def get_job(self, session_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.cursor().execute("SELECT * FROM jobs WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["required_skills"] = json.loads(data["required_skills"] or "[]")
            data["preferred_skills"] = json.loads(data["preferred_skills"] or "[]")
            data["education"] = json.loads(data["education"] or "[]")
            data["certifications"] = json.loads(data["certifications"] or "[]")
            return data

    def get_ranked_candidates(self, session_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.cursor().execute("""
            SELECT r.rank, r.total_score, r.tradeoff_note, r.component_scores, c.*
            FROM rankings r
            JOIN candidates c ON r.candidate_id = c.candidate_id AND r.session_id = c.session_id
            WHERE r.session_id = ?
            ORDER BY r.rank ASC
            """, (session_id,)).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["skills"] = json.loads(d.get("skills") or "[]")
                d["projects"] = json.loads(d.get("projects") or "[]")
                d["certifications"] = json.loads(d.get("certifications") or "[]")
                d["component_scores"] = json.loads(d.get("component_scores") or "[]")
                results.append(d)
            return results

    def get_candidate_verifications(self, session_id: str, candidate_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.cursor().execute("""
            SELECT * FROM verifications
            WHERE session_id = ? AND candidate_id = ?
            """, (session_id, candidate_id)).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["evidence"] = json.loads(d.get("evidence") or "[]")
                results.append(d)
            return results

    def save_chat_message(self, session_id: str, role: str, content: str, model: str = ""):
        with self._get_conn() as conn:
            conn.cursor().execute("""
            INSERT INTO chat_history (session_id, role, content, model)
            VALUES (?, ?, ?, ?)
            """, (session_id, role, content, model))
            conn.commit()

    def get_chat_history(self, session_id: str, limit: int = 10) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.cursor().execute("""
            SELECT role, content, model, timestamp FROM chat_history
            WHERE session_id = ?
            ORDER BY id ASC LIMIT ?
            """, (session_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def build_recruiter_context(self, session_id: str, query: str = "") -> str:
        """
        Retrieves recruitment memory and builds rich, grounded context for recruiter Q&A.
        """
        job = self.get_job(session_id)
        candidates = self.get_ranked_candidates(session_id)

        if not job and not candidates:
            return ""

        context_lines = []
        if job:
            context_lines.append(f"## Role: {job.get('role_title')} ({job.get('seniority_level')})")
            context_lines.append(f"Required Skills: {', '.join(job.get('required_skills', []))}")
            if job.get('preferred_skills'):
                context_lines.append(f"Preferred Skills: {', '.join(job.get('preferred_skills', []))}")
            context_lines.append(f"Experience Requirement: {job.get('experience_years')}\n")

        context_lines.append("## Screened & Ranked Candidates (Deterministic Scoring):")
        for c in candidates[:10]:
            cid = c["candidate_id"]
            verifs = self.get_candidate_verifications(session_id, cid)
            strong      = [v["jd_skill"] for v in verifs if v["status"] == "STRONGLY_SUPPORTED"]
            partial     = [v["jd_skill"] for v in verifs if v["status"] == "PARTIALLY_SUPPORTED"]
            unsupported = [v["jd_skill"] for v in verifs if v["status"] in ("UNSUPPORTED", "NOT_MENTIONED")]
            gh_supported = [v["jd_skill"] for v in verifs if v.get("github_status") == "SUPPORTED"]
            gh_url      = c.get("github_url", "")

            context_lines.append(
                f"#{c['rank']} {c['name']} (Score: {c['total_score']:.1f}/100, Exp: {c['total_experience_years']} yrs)"
                + (f" | GitHub: {gh_url}" if gh_url else "") + "\n"
                f"  🟢 Strong Resume Evidence: {', '.join(strong) if strong else 'None'}\n"
                f"  🟡 Partial/Skills Only: {', '.join(partial) if partial else 'None'}\n"
                f"  🔴 Missing/Unsupported: {', '.join(unsupported) if unsupported else 'None'}\n"
                + (f"  🐙 GitHub Corroborated: {', '.join(gh_supported)}\n" if gh_supported else "")
            )
        return "\n".join(context_lines)

    def get_latest_screening_dict(self) -> Optional[dict]:
        """
        Reconstructs the full ScreeningResult dictionary from the latest saved SQLite session.
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT session_id FROM jobs ORDER BY created_at DESC LIMIT 1").fetchone()
            if not row:
                return None
            session_id = row["session_id"]

        job = self.get_job(session_id)
        candidates_db = self.get_ranked_candidates(session_id)
        if not candidates_db:
            return None

        # Build ranked_list candidates
        ranked_candidates = []
        for c in candidates_db:
            cid = c["candidate_id"]
            verifs_raw = self.get_candidate_verifications(session_id, cid)
            skill_breakdown = []
            for v in verifs_raw:
                skill_breakdown.append({
                    "jd_skill": v["jd_skill"],
                    "status": v["status"],
                    "confidence_score": v["confidence_score"],
                    "explanation": v["explanation"],
                    "claim": {"skill": v["jd_skill"], "statement": v["claim_statement"]},
                    "evidence": v.get("evidence", []),
                })

            ranked_candidates.append({
                "rank": c["rank"],
                "tradeoff_note": c.get("tradeoff_note", ""),
                "score": {
                    "candidate_id": cid,
                    "candidate_name": c["name"],
                    "total_score": c["total_score"],
                    "relevant_years": c.get("total_experience_years", 0),
                    "component_scores": c.get("component_scores", []),
                    "skill_breakdown": skill_breakdown,
                    "skill_matches": [],
                    "profile": {
                        "name": c["name"],
                        "email": c.get("email", ""),
                        "phone": c.get("phone", ""),
                        "skills": c.get("skills", []),
                        "projects": c.get("projects", []),
                        "education": json.loads(c.get("education") or "[]") if isinstance(c.get("education"), str) else c.get("education", []),
                        "certifications": c.get("certifications", []),
                        "total_experience_years": c.get("total_experience_years", 0),
                    }
                }
            })

        gap_report = None
        feasibility_report = None
        tradeoff_shortlist = None
        with self._get_conn() as conn:
            row_ana = conn.cursor().execute("SELECT gap_report, feasibility_report, tradeoff_shortlist FROM analyses WHERE session_id = ?", (session_id,)).fetchone()
            if row_ana:
                if row_ana["gap_report"]:
                    try:
                        gap_report = json.loads(row_ana["gap_report"])
                    except Exception:
                        pass
                if row_ana["feasibility_report"]:
                    try:
                        feasibility_report = json.loads(row_ana["feasibility_report"])
                    except Exception:
                        pass
                if row_ana["tradeoff_shortlist"]:
                    try:
                        tradeoff_shortlist = json.loads(row_ana["tradeoff_shortlist"])
                    except Exception:
                        pass

        return {
            "session_id": session_id,
            "jd_analysis": job,
            "ranked_list": {
                "candidates": ranked_candidates,
                "jd_role": job.get("role_title", "Technical Role") if job else "Technical Role",
                "total_analyzed": len(ranked_candidates),
            },
            "gap_report": gap_report,
            "feasibility_report": feasibility_report,
            "tradeoff_shortlist": tradeoff_shortlist,
            "pipeline_stage": "complete",
            "progress_pct": 100.0,
            "progress_log": [f"[100%] ✓ Screening complete ({len(ranked_candidates)} candidates)"],
            "total_time_secs": 25.0,
            "error": None,
            "candidate_count": len(ranked_candidates),
        }

    def delete_candidate(self, candidate_id: str, session_id: str = None) -> bool:
        """Deletes a candidate and their verifications and rankings from SQLite memory."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute("DELETE FROM candidates WHERE candidate_id = ? AND session_id = ?", (candidate_id, session_id))
                cursor.execute("DELETE FROM rankings WHERE candidate_id = ? AND session_id = ?", (candidate_id, session_id))
                cursor.execute("DELETE FROM verifications WHERE candidate_id = ? AND session_id = ?", (candidate_id, session_id))
                # Re-rank remaining candidates for this session
                rows = cursor.execute(
                    "SELECT candidate_id FROM rankings WHERE session_id = ? ORDER BY total_score DESC",
                    (session_id,)
                ).fetchall()
                for new_rank, row in enumerate(rows, 1):
                    cursor.execute(
                        "UPDATE rankings SET rank = ? WHERE session_id = ? AND candidate_id = ?",
                        (new_rank, session_id, row["candidate_id"])
                    )
            else:
                cursor.execute("DELETE FROM candidates WHERE candidate_id = ?", (candidate_id,))
                cursor.execute("DELETE FROM rankings WHERE candidate_id = ?", (candidate_id,))
                cursor.execute("DELETE FROM verifications WHERE candidate_id = ?", (candidate_id,))
            conn.commit()
            print(f"[RecruitmentMemory] Deleted candidate {candidate_id} (session={session_id})")
            return True

    def clear_screening(self, session_id: str = None):
        """Clears screening data for a specific session or all sessions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute("DELETE FROM jobs WHERE session_id = ?", (session_id,))
                cursor.execute("DELETE FROM candidates WHERE session_id = ?", (session_id,))
                cursor.execute("DELETE FROM rankings WHERE session_id = ?", (session_id,))
                cursor.execute("DELETE FROM verifications WHERE session_id = ?", (session_id,))
                cursor.execute("DELETE FROM analyses WHERE session_id = ?", (session_id,))
                cursor.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
            else:
                cursor.execute("DELETE FROM jobs")
                cursor.execute("DELETE FROM candidates")
                cursor.execute("DELETE FROM rankings")
                cursor.execute("DELETE FROM verifications")
                cursor.execute("DELETE FROM analyses")
                cursor.execute("DELETE FROM chat_history")
            conn.commit()
            print(f"[RecruitmentMemory] Cleared screening memory for session: {session_id or 'ALL'}")
