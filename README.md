# ARIA Core — Talent Screening System

**ARIA Core** is an evidence-based, explainable candidate screening engine powered by a **Two-Model Architecture** (**Llama 3.2** local GPU + **Groq** cloud API), **PyMuPDF** document processing, **Pydantic** output validation, **deterministic Python scoring**, and **SQLite recruitment memory**.

---

## 🏗️ Architecture

```
                          Recruiter / Web UI
                                  │
                                  ▼
                         Flask / REST API
                                  │
                       Recruitment Orchestrator
                                  │
                            Smart Router
                           ┌──────┴──────┐
                           ▼             ▼
                      Llama 3.2        Groq API
                      Local GPU         Cloud
                   (Routine Tasks)  (Complex Reasoning)
                           │             │
                           └──────┬──────┘
                                  ▼
                        Evidence Verification
                       (🟢 / 🟡 / 🔴 / ⚪)
                                  │
                        Python Ranking Engine
                    (40% / 25% / 20% / 10% / 5%)
                                  │
                      SQLite Recruitment Memory
                     (Jobs, Candidates, Evidence,
                        Rankings, Chat History)
                                  │
                                  ▼
                 Grounded Recruiter Chat & Dashboard
```

---

## ⚡ Two-Model Architecture & Smart Router

| Backend | Model | Tasks Handled |
|---|---|---|
| **Local GPU (Ollama)** | **Llama 3.2** (`llama3.2:latest`) | JD parsing, resume extraction, claim extraction, basic evidence verification, candidate summaries |
| **Cloud (Groq API)** | **Llama 3.3 70B** (`llama-3.3-70b-versatile`) | Candidate-vs-candidate comparisons, trade-off analysis, complex gap reasoning, nuanced evidence evaluation |

*No need to keep multiple heavy local models loaded in VRAM.*

---

## 🔍 Core Innovations

### 1. Evidence-Based Verification
Instead of merely asking *"Does Candidate A know Python?"*, ARIA Core evaluates:
**"What concrete evidence in the candidate's application supports the claim?"**
- 🟢 **Strongly Supported**: Clear evidence (Certification + Production project / work experience).
- 🟡 **Partially Supported**: Mentioned only in the Skills section without project/work evidence.
- 🔴 **Unsupported**: Claimed but contradicted or unevidenced.
- ⚪ **Not Mentioned**: Skill not present in the candidate application.

### 2. Deterministic Python Ranking Engine
No LLM hallucination in final numerical ranks:
- **Required Skills Coverage**: `40%`
- **Relevant Experience**: `25%`
- **Evidence Strength**: `20%`
- **Preferred Skills**: `10%`
- **Education Match**: `5%`

### 3. Lightweight Pipeline
- **PyMuPDF (`fitz`)** and **python-docx** for high-performance text extraction without LLM cost.
- Direct taxonomy & section matching without heavy SentenceTransformers or FAISS overhead.
- **Pydantic** schema validation (`JDAnalysisSchema`, `ResumeAnalysisSchema`).

### 4. SQLite Recruitment Memory
All jobs, candidate profiles, evidence verifications, scores, and trade-off notes are persisted in `data/recruitment.db`.
Recruiters can ask questions in the **Chat Window** (e.g. *"Why is Candidate A ranked above Candidate B?"*) and get instantaneous, grounded responses retrieved directly from memory without re-running the screening pipeline.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install flask flask-cors python-dotenv ollama pymupdf python-docx groq pydantic
```

### 2. Configure Environment (`.env`)
```ini
GROQ_API_KEY=your_groq_api_key_here
LOCAL_MODEL=llama3.2:latest
GROQ_MODEL=llama-3.3-70b-versatile
PORT=5000
```

### 3. Verify Local Ollama Model
Ensure Ollama is running with Llama 3.2:
```bash
ollama pull llama3.2
```

### 4. Run Smoke Tests
```bash
python test_recruitment_smoke.py
```

### 5. Start the Server
```bash
python server.py
```
Open `http://localhost:5000` (or `index.html`) in your browser.

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Server & LLM backend health status |
| `POST` | `/api/recruitment/upload-jd` | Upload and extract Job Description |
| `POST` | `/api/recruitment/upload-resumes` | Upload candidate resumes (PDF/DOCX) |
| `POST` | `/api/recruitment/analyze` | Launch screening pipeline in background |
| `GET` | `/api/recruitment/status/<run_id>` | Poll screening pipeline progress & logs |
| `GET` | `/api/recruitment/results/<run_id>` | Retrieve full screening results & rankings |
| `GET` | `/api/recruitment/candidate/<id>` | Single candidate evidence breakdown |
| `POST` | `/api/recruitment/compare` | Head-to-head candidate trade-off comparison |
| `GET` | `/api/recruitment/gaps/<run_id>` | Applicant pool skill gap analytics |
| `POST` | `/api/chat` | Recruiter Q&A grounded in SQLite memory |
