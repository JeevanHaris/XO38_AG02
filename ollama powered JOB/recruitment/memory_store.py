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
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

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
                (candidate_id, session_id, name, email, phone, skills, experience_entries, total_experience_years, projects, education, certifications, raw_claims, raw_text, filename)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        cursor.execute("""
                        INSERT INTO verifications
                        (session_id, candidate_id, jd_skill, claim_statement, status, confidence_score, explanation, evidence)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            session_id,
                            s.candidate_id,
                            v.jd_skill,
                            v.claim.statement if v.claim else "",
                            v.status.value,
                            v.confidence_score,
                            v.explanation,
                            json.dumps([e.to_dict() for e in v.evidence]),
                        ))

            # Save Gap Analysis
            if result.gap_report:
                cursor.execute("""
                INSERT OR REPLACE INTO analyses
                (session_id, gap_report, summary, total_candidates)
                VALUES (?, ?, ?, ?)
                """, (
                    session_id,
                    json.dumps(result.gap_report.to_dict()),
                    result.gap_report.summary,
                    result.gap_report.total_candidates,
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
            strong = [v["jd_skill"] for v in verifs if v["status"] == "STRONGLY_SUPPORTED"]
            partial = [v["jd_skill"] for v in verifs if v["status"] == "PARTIALLY_SUPPORTED"]
            unsupported = [v["jd_skill"] for v in verifs if v["status"] in ("UNSUPPORTED", "NOT_MENTIONED")]

            context_lines.append(
                f"#{c['rank']} {c['name']} (Score: {c['total_score']:.1f}/100, Exp: {c['total_experience_years']} yrs)\n"
                f"  🟢 Strong Evidence: {', '.join(strong) if strong else 'None'}\n"
                f"  🟡 Partial/Skills Only: {', '.join(partial) if partial else 'None'}\n"
                f"  🔴 Missing/Unsupported: {', '.join(unsupported) if unsupported else 'None'}"
            )
            if c.get("tradeoff_note"):
                context_lines.append(f"  Note: {c['tradeoff_note']}")

        return "\n".join(context_lines)
