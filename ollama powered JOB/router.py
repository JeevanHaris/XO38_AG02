"""
RecruitScreen / ARIA Core — Smart Recruitment Router
────────────────────────────────────────────────────
Routes tasks between Llama 3.2 (Local GPU) and Groq API (Cloud) based on task complexity.

Two-Model Architecture:
  Routine Tasks -> Llama 3.2 (Local GPU):
    - jd_extraction
    - resume_extraction
    - skill_extraction
    - claim_extraction
    - basic_evidence_check
    - candidate_summaries
    - chat (grounded Q&A)

  Complex Tasks -> Groq API (Cloud):
    - difficult_evidence_verification
    - candidate_vs_candidate_comparison (complex_comparison)
    - tradeoff_analysis
    - complex_requirement_gap_reasoning
    - final_explanation (complex_explanation)
"""

import os

LLAMA_ROUTINE_TASKS = {
    "jd_extraction",
    "resume_extraction",
    "skill_extraction",
    "claim_extraction",
    "basic_evidence_check",
    "candidate_summaries",
    "extraction",
    "verification_simple",
    "requirement_conflict_detection",
    "chat",
}

GROQ_COMPLEX_TASKS = {
    "difficult_evidence_verification",
    "complex_comparison",
    "tradeoff_analysis",
    "complex_requirement_gap_reasoning",
    "requirement_conflict_ambiguous",
    "tradeoff_narrative",
    "final_explanation",
    "complex_explanation",
    "comparison",
    "complex_reasoning",
}


class RoutingDecision:
    """Result of one routing decision."""

    def __init__(self, model, task_type, provider="ollama",
                 confidence=1.0, reason=""):
        self.model      = model
        self.task_type  = task_type
        self.provider   = provider
        self.confidence = confidence
        self.reason     = reason

    def to_dict(self):
        return {
            "model":      self.model,
            "task_type":  self.task_type,
            "provider":   self.provider,
            "confidence": round(self.confidence, 2),
            "reason":     self.reason,
        }


class ModelRouter:
    """Routes recruitment tasks to Llama 3.2 (Local) or Groq API (Cloud)."""

    def __init__(
        self,
        default_model:    str = None,
        default_provider: str = "ollama",
        groq_enabled:     bool = True,
    ):
        self.local_model      = default_model or os.environ.get("LOCAL_MODEL", "llama3.2:latest")
        self.groq_model       = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        self.default_model    = self.local_model
        self.default_provider = default_provider
        self.groq_enabled     = groq_enabled
        self._route_log: list[dict] = []

    def route_task(self, task: str) -> RoutingDecision:
        """Direct programmatic routing based on task name."""
        if task in LLAMA_ROUTINE_TASKS:
            return RoutingDecision(
                model=self.local_model,
                task_type=task,
                provider="ollama",
                confidence=1.0,
                reason=f"Routine task '{task}' routed to local Llama 3.2",
            )
        elif task in GROQ_COMPLEX_TASKS:
            if self.groq_enabled:
                return RoutingDecision(
                    model=self.groq_model,
                    task_type=task,
                    provider="groq",
                    confidence=1.0,
                    reason=f"Complex task '{task}' routed to Groq Cloud API",
                )
            else:
                return RoutingDecision(
                    model=self.local_model,
                    task_type=task,
                    provider="ollama",
                    confidence=0.7,
                    reason=f"Complex task '{task}' routed to local Llama 3.2 (Groq disabled)",
                )
        # Default fallback to Llama 3.2
        return RoutingDecision(
            model=self.local_model,
            task_type=task or "routine",
            provider="ollama",
            confidence=0.8,
            reason="Defaulted to local Llama 3.2",
        )

    def route(self, task_text: str, task_type_hint: str = None,
              force_model: str = None, force_provider: str = None) -> RoutingDecision:
        """
        Determine which model + provider should handle this task.
        """
        if force_model:
            decision = RoutingDecision(
                model=force_model,
                task_type=task_type_hint or "user_selected",
                provider=force_provider or self.default_provider,
                confidence=1.0,
                reason=f"Forced to {force_provider or 'ollama'}/{force_model}",
            )
            self._log(task_text, decision)
            return decision

        if task_type_hint:
            decision = self.route_task(task_type_hint)
            self._log(task_text, decision)
            return decision

        # Infer from prompt keywords
        lower = (task_text or "").lower()
        if any(w in lower for w in ["compare", "versus", "tradeoff", "trade-off", "trade off", "who is better"]):
            decision = self.route_task("complex_comparison")
        elif any(w in lower for w in ["gap analysis", "missing in pool", "pool risk"]):
            decision = self.route_task("complex_requirement_gap_reasoning")
        elif any(w in lower for w in ["extract", "parse", "resume", "job description"]):
            decision = self.route_task("extraction")
        else:
            decision = self.route_task("chat")

        self._log(task_text, decision)
        return decision

    def _log(self, text: str, decision: RoutingDecision):
        self._route_log.append({
            "task_preview": (text[:60] + "...") if len(text) > 60 else text,
            "decision":     decision.to_dict(),
        })

    def get_recent_routes(self, n=10) -> list[dict]:
        return self._route_log[-n:]
