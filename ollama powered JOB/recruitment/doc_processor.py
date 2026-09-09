"""
RecruitScreen v1.0 — Document Processor
─────────────────────────────────────────
Ingests and preprocesses Job Descriptions and Resumes.
Reuses ARIA's proven _extract_text() core logic for PDF/DOCX/TXT.

Usage:
    processor = DocumentProcessor()
    jd  = processor.process_jd("jd.pdf", pdf_bytes)
    candidates = processor.batch_process_resumes(file_list)
"""

import os
import io
import uuid
import re


class DocumentProcessor:
    """Extracts and preprocesses text from JD and resume files."""

    ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".rst", ".csv"}

    # ── Text Extraction ────────────────────────────────────────────────

    @staticmethod
    def extract_text(filename: str, file_bytes: bytes) -> str:
        """
        Extract plain text from PDF, DOCX, or TXT file bytes.
        Reuses ARIA's proven extraction logic.
        """
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_bytes))
                pages  = [page.extract_text() or "" for page in reader.pages]
                return "\n".join(pages).strip()
            except ImportError:
                return "[ERROR] pypdf not installed. Run: pip install pypdf"
            except Exception as e:
                return f"[ERROR] Could not read PDF: {e}"

        if ext == ".docx":
            try:
                from docx import Document
                doc = Document(io.BytesIO(file_bytes))
                return "\n".join(
                    p.text for p in doc.paragraphs if p.text.strip()
                ).strip()
            except ImportError:
                return "[ERROR] python-docx not installed. Run: pip install python-docx"
            except Exception as e:
                return f"[ERROR] Could not read DOCX: {e}"

        if ext in (".txt", ".md", ".markdown", ".rst", ".csv"):
            try:
                return file_bytes.decode("utf-8", errors="replace").strip()
            except Exception as e:
                return f"[ERROR] Could not read file: {e}"

        return f"[ERROR] Unsupported file type: {ext}"

    # ── JD Processing ─────────────────────────────────────────────────

    def process_jd(self, filename: str, file_bytes: bytes) -> dict:
        """
        Process a job description file.

        Returns:
            {
              "raw_text":   str,
              "filename":   str,
              "word_count": int,
              "char_count": int,
              "error":      str | None,
            }
        """
        text = self.extract_text(filename, file_bytes)

        if text.startswith("[ERROR]"):
            return {"raw_text": "", "filename": filename,
                    "word_count": 0, "char_count": 0, "error": text}

        return {
            "raw_text":   text,
            "filename":   filename,
            "word_count": len(text.split()),
            "char_count": len(text),
            "error":      None,
        }

    # ── Resume Processing ──────────────────────────────────────────────

    def process_resume(self, filename: str, file_bytes: bytes) -> dict:
        """
        Process a single resume file.

        Returns:
            {
              "candidate_id":    str (UUID),
              "raw_text":        str,
              "filename":        str,
              "candidate_name":  str (inferred),
              "word_count":      int,
              "char_count":      int,
              "error":           str | None,
            }
        """
        text = self.extract_text(filename, file_bytes)

        if text.startswith("[ERROR]"):
            return {
                "candidate_id":   str(uuid.uuid4()),
                "raw_text":       "",
                "filename":       filename,
                "candidate_name": self._name_from_filename(filename),
                "word_count":     0,
                "char_count":     0,
                "error":          text,
            }

        candidate_name = self._infer_candidate_name(filename, text)

        return {
            "candidate_id":   str(uuid.uuid4()),
            "raw_text":       text,
            "filename":       filename,
            "candidate_name": candidate_name,
            "word_count":     len(text.split()),
            "char_count":     len(text),
            "error":          None,
        }

    def batch_process_resumes(
        self, files: list[tuple[str, bytes]]
    ) -> list[dict]:
        """
        Process multiple resume files.

        Args:
            files: list of (filename, file_bytes) tuples

        Returns:
            list of processed resume dicts (in order, errors included)
        """
        results = []
        for filename, file_bytes in files:
            result = self.process_resume(filename, file_bytes)
            results.append(result)
            status = "OK" if not result["error"] else f"ERROR: {result['error']}"
            print(f"[DocProcessor] Resume: {filename} — {status} "
                  f"({result['char_count']:,} chars)")
        return results

    # ── Name Inference ────────────────────────────────────────────────

    @staticmethod
    def _name_from_filename(filename: str) -> str:
        """Guess candidate name from filename: 'john_doe_resume.pdf' → 'John Doe'."""
        base = os.path.splitext(os.path.basename(filename))[0]
        # Remove common suffixes
        base = re.sub(
            r"[-_](resume|cv|application|apply|candidate|2024|2025|2026|v\d+)$",
            "", base, flags=re.IGNORECASE
        )
        # Replace separators with spaces and title-case
        name = re.sub(r"[-_]+", " ", base).strip().title()
        return name or "Unknown Candidate"

    @staticmethod
    def _infer_candidate_name(filename: str, text: str) -> str:
        """
        Attempt to extract candidate name from the document text first line
        or filename as fallback.
        """
        # Try first non-empty line (often the name in resumes)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            first_line = lines[0]
            # Heuristic: name is short (≤5 words), all caps or title case, no digits
            words = first_line.split()
            if (
                2 <= len(words) <= 5
                and not re.search(r"\d", first_line)
                and not any(kw in first_line.lower() for kw in
                            ["resume", "curriculum", "profile", "summary",
                             "objective", "contact", "email", "phone"])
            ):
                return first_line.title()

        # Fallback: derive from filename
        return DocumentProcessor._name_from_filename(filename)

    # ── Validation ────────────────────────────────────────────────────

    def validate_file(self, filename: str) -> tuple[bool, str]:
        """Check if a file extension is supported."""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            return False, (
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )
        return True, ""
