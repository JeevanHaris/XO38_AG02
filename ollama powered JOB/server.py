"""
RecruitScreen v1.0 — Flask Backend
────────────────────────────────────
Agentic Talent Screening & Evidence Verification Platform
Built on ARIA Core (stripped and specialized).

API Endpoints:
  POST /api/recruitment/upload-jd          Upload job description
  POST /api/recruitment/upload-resumes     Upload multiple resumes
  POST /api/recruitment/analyze            Start screening pipeline
  GET  /api/recruitment/status/{run_id}    Poll pipeline progress (SSE)
  GET  /api/recruitment/results/{run_id}   Full results JSON
  GET  /api/recruitment/candidate/{id}     Single candidate detail
  POST /api/recruitment/compare            Compare two candidates
  GET  /api/recruitment/gaps/{run_id}      Gap analysis report
  POST /api/chat                           Recruiter Q&A chat
  GET  /api/health                         Health check

Setup:
    pip install flask flask-cors ollama pypdf python-docx sentence-transformers groq
    pip install faiss-cpu numpy
    
    # Set environment variables (or use .env):
    GROQ_API_KEY=your_key_here

Run:
    python server.py
    Then open index.html in browser.
"""

import os
import sys
import uuid
import time
import json
import threading

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Suppress HuggingFace symlinks warning
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── Gateway + Router ─────────────────────────────────────────────────
from gateway import MultiGateway
from router  import ModelRouter

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
LOCAL_MODEL    = os.environ.get("LOCAL_MODEL", "llama3.2:latest")
GROQ_MODEL     = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

gateway = MultiGateway(
    ollama_default_model = LOCAL_MODEL,
    groq_api_key         = GROQ_API_KEY,
    groq_default_model   = GROQ_MODEL,
)

router = ModelRouter(
    default_model = LOCAL_MODEL,
    groq_enabled  = bool(GROQ_API_KEY),
)

# ─── Recruitment Orchestrator ─────────────────────────────────────────
from recruitment.orchestrator import RecruitmentOrchestrator
orchestrator = RecruitmentOrchestrator(gateway=gateway, router=router)

# ─── Flask App ────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

# ─── In-Memory Session Store ──────────────────────────────────────────
# run_id → {result: ScreeningResult, thread: Thread, done: bool, error: str}
_sessions: dict[str, dict] = {}

# Temp file store for uploaded docs (before analysis)
# session_id → {jd: (filename, bytes), resumes: [(filename, bytes)]}
_upload_store: dict[str, dict] = {}

print("=" * 60)
print(" RecruitScreen v1.0 — Agentic Talent Screening")
print("=" * 60)
print(f"  Local model:  {LOCAL_MODEL}")
print(f"  Groq model:   {GROQ_MODEL}")
print(f"  Groq enabled: {bool(GROQ_API_KEY)}")
print(f"  Ollama:       {'✓ Running' if gateway.ollama.is_available() else '✗ Not found'}")
print("=" * 60)


from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory

# ─── Static UI & Health Check ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    if "text/html" in request.headers.get("Accept", ""):
        return send_from_directory(".", "index.html")
    return health()

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status":        "ok",
        "service":       "RecruitScreen v1.0",
        "ollama":        gateway.ollama.is_available(),
        "groq_enabled":  bool(GROQ_API_KEY),
        "local_model":   LOCAL_MODEL,
        "groq_model":    GROQ_MODEL,
    })

@app.route("/style.css", methods=["GET"])
def serve_css():
    return send_from_directory(".", "style.css", mimetype="text/css")

@app.route("/app.js", methods=["GET"])
def serve_js():
    return send_from_directory(".", "app.js", mimetype="application/javascript")


# ─── Upload Job Description ───────────────────────────────────────────
@app.route("/api/recruitment/upload-jd", methods=["POST"])
def upload_jd():
    """Accept a JD file and store it for the screening session."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f          = request.files["file"]
    session_id = request.form.get("session_id") or str(uuid.uuid4())

    file_bytes = f.read()
    filename   = f.filename

    from recruitment.doc_processor import DocumentProcessor
    proc = DocumentProcessor()
    ok, err = proc.validate_file(filename)
    if not ok:
        return jsonify({"error": err}), 415

    # Preview the JD text
    doc = proc.process_jd(filename, file_bytes)
    if doc["error"]:
        return jsonify({"error": doc["error"]}), 422

    if session_id not in _upload_store:
        _upload_store[session_id] = {"jd": None, "resumes": []}

    _upload_store[session_id]["jd"] = (filename, file_bytes)

    print(f"[Server] JD uploaded: {filename} ({doc['char_count']:,} chars) "
          f"session={session_id}")

    return jsonify({
        "session_id": session_id,
        "filename":   filename,
        "word_count": doc["word_count"],
        "char_count": doc["char_count"],
        "preview":    doc["raw_text"][:500],
    })


# ─── Upload Resumes ───────────────────────────────────────────────────
@app.route("/api/recruitment/upload-resumes", methods=["POST"])
def upload_resumes():
    """Accept multiple resume files for a session."""
    session_id = request.form.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    from recruitment.doc_processor import DocumentProcessor
    proc = DocumentProcessor()

    if session_id not in _upload_store:
        _upload_store[session_id] = {"jd": None, "resumes": []}

    accepted = []
    rejected = []

    for f in files:
        ok, err = proc.validate_file(f.filename)
        if not ok:
            rejected.append({"filename": f.filename, "error": err})
            continue

        file_bytes = f.read()
        _upload_store[session_id]["resumes"].append((f.filename, file_bytes))
        accepted.append(f.filename)

    print(f"[Server] Resumes uploaded: {len(accepted)} accepted, "
          f"{len(rejected)} rejected. session={session_id}")

    return jsonify({
        "session_id":    session_id,
        "accepted":      accepted,
        "rejected":      rejected,
        "total_resumes": len(_upload_store[session_id]["resumes"]),
    })


# ─── Start Analysis ───────────────────────────────────────────────────
@app.route("/api/recruitment/analyze", methods=["POST"])
def analyze():
    """Trigger the full screening pipeline in a background thread."""
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id or session_id not in _upload_store:
        return jsonify({"error": "Invalid or missing session_id"}), 400

    upload = _upload_store[session_id]

    if not upload.get("jd"):
        return jsonify({"error": "No job description uploaded for this session"}), 400

    if not upload.get("resumes"):
        return jsonify({"error": "No resumes uploaded for this session"}), 400

    # Generate run_id
    run_id = str(uuid.uuid4())

    _sessions[run_id] = {
        "session_id": session_id,
        "done":       False,
        "result":     None,
        "error":      None,
        "started_at": time.time(),
    }

    def run():
        try:
            from recruitment.models import ScreeningResult

            def progress_cb(result: ScreeningResult):
                _sessions[run_id]["result"] = result

            result = orchestrator.run_screening(
                jd_file      = upload["jd"],
                resume_files = upload["resumes"],
                session_id   = session_id,
                progress_cb  = progress_cb,
            )
            _sessions[run_id]["result"] = result
            _sessions[run_id]["done"]   = True

        except Exception as e:
            _sessions[run_id]["error"] = str(e)
            _sessions[run_id]["done"]  = True
            print(f"[Server] Pipeline error for run {run_id}: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    _sessions[run_id]["thread"] = t

    print(f"[Server] Pipeline started: run_id={run_id}, "
          f"session={session_id}, "
          f"resumes={len(upload['resumes'])}")

    return jsonify({
        "run_id":     run_id,
        "session_id": session_id,
        "status":     "started",
        "message":    f"Screening pipeline started for {len(upload['resumes'])} candidates",
    })


# ─── Pipeline Status (SSE-compatible polling) ─────────────────────────
@app.route("/api/recruitment/status/<run_id>", methods=["GET"])
def pipeline_status(run_id: str):
    """Poll the current pipeline status and progress."""
    if run_id not in _sessions:
        return jsonify({"error": "Unknown run_id"}), 404

    session  = _sessions[run_id]
    result   = session.get("result")
    done     = session.get("done", False)
    error    = session.get("error")

    if error and not result:
        return jsonify({
            "run_id":   run_id,
            "done":     True,
            "error":    error,
            "stage":    "failed",
            "progress": 0,
        })

    if not result:
        return jsonify({
            "run_id":   run_id,
            "done":     False,
            "stage":    "starting",
            "progress": 0,
            "log":      [],
        })

    return jsonify({
        "run_id":   run_id,
        "done":     done,
        "stage":    result.pipeline_stage.value,
        "progress": result.progress_pct,
        "log":      result.progress_log[-5:],   # last 5 log entries
        "error":    result.error,
        "candidate_count": len(result.candidates),
    })


# ─── Full Results ─────────────────────────────────────────────────────
@app.route("/api/recruitment/results/<run_id>", methods=["GET"])
def get_results(run_id: str):
    """Return the full screening result once the pipeline is done."""
    if run_id not in _sessions:
        return jsonify({"error": "Unknown run_id"}), 404

    session = _sessions[run_id]
    result  = session.get("result")

    if not session.get("done"):
        return jsonify({"error": "Pipeline still running", "done": False}), 202

    if not result:
        return jsonify({"error": session.get("error", "Unknown error")}), 500

    return jsonify(result.to_dict())


# ─── Latest Completed Screening Result ─────────────────────────────────
@app.route("/api/recruitment/latest", methods=["GET"])
def get_latest_result():
    """Return the most recent completed screening result."""
    # 1. From active in-memory sessions (latest first)
    for run_id in reversed(list(_sessions.keys())):
        session = _sessions[run_id]
        if session.get("done") and session.get("result"):
            return jsonify(session["result"].to_dict())

    # 2. Check any session with ranked candidates
    for run_id, sess in _sessions.items():
        if sess.get("result") and sess["result"].ranked_list:
            return jsonify(sess["result"].to_dict())

    # 3. From SQLite Recruitment Memory
    try:
        latest_from_db = orchestrator.memory.get_latest_screening_dict()
        if latest_from_db:
            return jsonify(latest_from_db)
    except Exception as e:
        print(f"[Server] SQLite get_latest_screening_dict error: {e}")

    return jsonify({"error": "No completed screening found", "candidates": []}), 404


# ─── Single Candidate Detail ──────────────────────────────────────────
@app.route("/api/recruitment/candidate/<candidate_id>", methods=["GET"])
def get_candidate(candidate_id: str):
    """Return detailed analysis for a single candidate."""
    run_id = request.args.get("run_id")
    result = None

    if run_id and run_id in _sessions:
        result = _sessions[run_id].get("result")
    else:
        # Fallback to the latest active in-memory session with results
        for sid in reversed(list(_sessions.keys())):
            sess = _sessions[sid]
            if sess.get("result") and sess["result"].ranked_list:
                result = sess["result"]
                break

    # 1. Search in active in-memory result
    if result and result.ranked_list:
        for ranked in result.ranked_list.candidates:
            if ranked.score.candidate_id == candidate_id:
                return jsonify({
                    "rank":           ranked.rank,
                    "score":          ranked.score.to_dict(),
                    "tradeoff_note":  ranked.tradeoff_note,
                })

    # 2. Search in SQLite Recruitment Memory
    try:
        latest_db = orchestrator.memory.get_latest_screening_dict()
        if latest_db and "ranked_list" in latest_db and latest_db["ranked_list"]:
            for c in latest_db["ranked_list"].get("candidates", []):
                if c.get("score", {}).get("candidate_id") == candidate_id:
                    return jsonify(c)
    except Exception as e:
        print(f"[Server] get_candidate DB fallback error: {e}")

    return jsonify({"error": "Candidate not found"}), 404


# ─── Compare Two Candidates ───────────────────────────────────────────
@app.route("/api/recruitment/compare", methods=["POST"])
def compare_candidates():
    """Generate a detailed comparison between two candidates."""
    data = request.get_json(silent=True) or {}
    run_id  = data.get("run_id")
    id_a    = data.get("candidate_a")
    id_b    = data.get("candidate_b")

    if not all([id_a, id_b]):
        return jsonify({"error": "candidate_a and candidate_b are required"}), 400

    result = None
    if run_id and run_id in _sessions:
        result = _sessions[run_id].get("result")
    else:
        for sid in reversed(list(_sessions.keys())):
            sess = _sessions[sid]
            if sess.get("result") and sess["result"].ranked_list:
                result = sess["result"]
                break

    if not result or not result.ranked_list:
        return jsonify({"error": "Results not ready"}), 202

    # Find both candidates
    score_map = {
        r.score.candidate_id: r.score
        for r in result.ranked_list.candidates
    }

    score_a = score_map.get(id_a)
    score_b = score_map.get(id_b)

    if not score_a or not score_b:
        return jsonify({"error": "One or both candidates not found"}), 404

    comparison = orchestrator.comparator.generate_comparison(
        score_a, score_b, result.jd_analysis
    )
    return jsonify(comparison)


# ─── Gap Analysis ─────────────────────────────────────────────────────
@app.route("/api/recruitment/gaps/<run_id>", methods=["GET"])
def get_gaps(run_id: str):
    """Return the skill gap analysis report."""
    if run_id not in _sessions:
        return jsonify({"error": "Unknown run_id"}), 404

    result = _sessions[run_id].get("result")
    if not result or not result.gap_report:
        return jsonify({"error": "Gap analysis not ready"}), 202

    return jsonify(result.gap_report.to_dict())


# ─── Recruiter Chat ───────────────────────────────────────────────────
CHAT_SYSTEM = """You are a recruitment AI assistant. You help recruiters understand candidate analyses.

Answer questions ONLY based on the provided candidate analysis data.
Be specific and cite evidence. Do NOT invent information not in the data.
Keep answers concise and factual."""


@app.route("/api/chat", methods=["POST"])
def chat():
    """Recruiter Q&A chat grounded in the stored analysis results."""
    data       = request.get_json(silent=True) or {}
    messages   = data.get("messages", [])
    run_id     = data.get("run_id")

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    user_query = messages[-1].get("content", "")
    session_id = data.get("session_id")
    if not session_id and run_id and run_id in _sessions:
        session_id = _sessions[run_id].get("session_id")

    # 1. Retrieve grounded context from SQLite Recruitment Memory
    context = ""
    if session_id:
        try:
            context = orchestrator.memory.build_recruiter_context(session_id, user_query)
        except Exception as e:
            print(f"[Server] SQLite memory retrieval error: {e}")

    # Fallback to in-memory active session if SQLite memory had no entries yet
    if not context and run_id and run_id in _sessions:
        result = _sessions[run_id].get("result")
        if result and result.ranked_list:
            context_parts = ["## Current Screening Results:\n"]
            jd = result.jd_analysis
            if jd:
                context_parts.append(
                    f"Job: {jd.role_title}\n"
                    f"Required Skills: {', '.join(jd.required_skills[:10])}\n\n"
                )
            context_parts.append("### Ranked Candidates:\n")
            for rc in result.ranked_list.candidates[:10]:
                s = rc.score
                strong = [
                    v.jd_skill for v in s.skill_breakdown
                    if v.status.value == "STRONGLY_SUPPORTED"
                ]
                missing = [
                    v.jd_skill for v in s.skill_breakdown
                    if v.status.value in ("NOT_MENTIONED", "UNSUPPORTED")
                ]
                context_parts.append(
                    f"#{rc.rank} {s.candidate_name} — Score: {s.total_score:.0f}/100\n"
                    f"  🟢 Strong evidence: {', '.join(strong[:5]) or 'None'}\n"
                    f"  🔴 Missing: {', '.join(missing[:5]) or 'None'}\n"
                )
            context = "".join(context_parts)

    system = CHAT_SYSTEM + (f"\n\n{context}" if context else "")
    llm_messages = [{"role": "system", "content": system}] + messages

    # Route: if comparing or asking why candidate A > candidate B -> Groq, else Llama 3.2
    is_comparative = any(w in user_query.lower() for w in ["why is", "compare", "above", "better than", "versus", "tradeoff", "trade-off"])
    task_hint = "complex_comparison" if is_comparative else "chat"

    try:
        decision = router.route(user_query, task_type_hint=task_hint)
        response = gateway.call(
            decision.model, llm_messages, provider=decision.provider
        )

        # Save to SQLite memory
        if session_id:
            try:
                orchestrator.memory.save_chat_message(session_id, "user", user_query)
                orchestrator.memory.save_chat_message(session_id, "assistant", response.content, model=response.model)
            except Exception:
                pass

        return jsonify({
            "content":  response.content,
            "model":    response.model,
            "provider": response.provider,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Run ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n[Server] Starting on http://localhost:{port}")
    print(f"[Server] Open index.html in your browser\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)