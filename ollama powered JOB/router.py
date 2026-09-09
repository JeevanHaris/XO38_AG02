"""
RecruitScreen v1.0 — Smart Recruitment Router
───────────────────────────────────────────────
Routes tasks to the correct model + provider based on task complexity.

Routing logic:
  extraction          → Ollama qwen3:4b    (JD parsing, resume parsing, claim extraction)
  verification_simple → Ollama qwen3:4b    (straightforward claim-evidence matching)
  verification_complex → Groq llama-3.3-70b (ambiguous evidence, nuanced matching)
  comparison          → Groq llama-3.3-70b  (multi-candidate trade-off analysis)
  chat                → Ollama qwen3:4b    (recruiter Q&A, grounded in analysis)
"""

import os

# ─── Recruitment Routing Table ────────────────────────────────────────

RECRUITMENT_ROUTING_TABLE = [
    {
        "task":        "extraction",
        "model":       os.environ.get("LOCAL_MODEL", "qwen3:4b"),
        "provider":    "ollama",
        "signals": [
            "extract", "parse", "identify", "list skills", "find requirements",
            "job description", "resume", "education", "certifications",
            "experience", "analyze jd", "analyze resume", "claims",
        ],
        "description": "JD extraction, resume parsing, claim extraction",
    },
    {
        "task":        "verification_simple",
        "model":       os.environ.get("LOCAL_MODEL", "qwen3:4b"),
        "provider":    "ollama",
        "signals": [
            "verify", "check claim", "evidence", "supported", "mentioned",
            "does the resume", "confirm", "validate",
        ],
        "description": "Straightforward claim-evidence verification",
    },
    {
        "task":        "comparison",
        "model":       os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "provider":    "groq",
        "signals": [
            "compare candidates", "trade-off", "tradeoff", "who is better",
            "best candidate", "rank", "versus", "relative to", "compared to",
            "stronger", "weaker", "differences between candidates",
        ],
        "description": "Multi-candidate comparison and trade-off analysis (Groq)",
    },
    {
        "task":        "complex_reasoning",
        "model":       os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "provider":    "groq",
        "signals": [
            "interpret", "ambiguous", "unclear", "infer", "explain why",
            "complex", "nuanced", "borderline", "partial", "interpret this",
        ],
        "description": "Complex evidence interpretation (Groq)",
    },
    {
        "task":        "chat",
        "model":       os.environ.get("LOCAL_MODEL", "qwen3:4b"),
        "provider":    "ollama",
        "signals": [],   # default fallback
        "description": "Recruiter Q&A chat (grounded in stored analysis)",
    },
]


# ─── Router ───────────────────────────────────────────────────────────

class RoutingDecision:
    """Result of one routing decision."""

    def __init__(self, model, task_type, provider="ollama",
                 confidence=0.5, reason=""):
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
    """Routes recruitment tasks to the optimal model and provider."""

    def __init__(
        self,
        default_model:    str = None,
        default_provider: str = "ollama",
        groq_enabled:     bool = True,
    ):
        self.default_model    = default_model or os.environ.get("LOCAL_MODEL", "qwen3:4b")
        self.default_provider = default_provider
        self.groq_enabled     = groq_enabled
        self._routing_table   = RECRUITMENT_ROUTING_TABLE
        self._route_log: list[dict] = []

    def route(self, task_text: str, task_type_hint: str = None,
              force_model: str = None, force_provider: str = None) -> RoutingDecision:
        """
        Determine which model + provider should handle this task.

        Args:
            task_text:       The text/prompt for the task.
            task_type_hint:  Explicit task type override (e.g. "extraction").
            force_model:     Bypass routing, use this model.
            force_provider:  Bypass routing, use this provider.
        """
        # Explicit override
        if force_model:
            decision = RoutingDecision(
                model=force_model,
                task_type="user_selected",
                provider=force_provider or self.default_provider,
                confidence=1.0,
                reason=f"Forced to {force_provider or 'ollama'}/{force_model}",
            )
            self._log(task_text, decision)
            return decision

        # Use hint if provided
        if task_type_hint:
            for entry in self._routing_table:
                if entry["task"] == task_type_hint:
                    # If Groq not enabled, fall back to Ollama
                    provider = entry["provider"]
                    model    = entry["model"]
                    if provider == "groq" and not self.groq_enabled:
                        provider = "ollama"
                        model    = self.default_model
                    decision = RoutingDecision(
                        model=model,
                        task_type=entry["task"],
                        provider=provider,
                        confidence=1.0,
                        reason=f"Task type hint: {task_type_hint}",
                    )
                    self._log(task_text, decision)
                    return decision

        # Keyword/heuristic routing
        text_lower = task_text.lower()
        best_match = None
        best_score = 0

        for entry in self._routing_table:
            if not entry["signals"]:
                continue
            hits = sum(1 for s in entry["signals"] if s in text_lower)
            if hits > best_score:
                best_score = hits
                best_match = entry

        if best_match and best_score > 0:
            provider = best_match["provider"]
            model    = best_match["model"]
            if provider == "groq" and not self.groq_enabled:
                provider = "ollama"
                model    = self.default_model
            matched = [s for s in best_match["signals"] if s in text_lower]
            decision = RoutingDecision(
                model=model,
                task_type=best_match["task"],
                provider=provider,
                confidence=min(best_score / 3.0, 1.0),
                reason=f"Matched: {', '.join(matched[:4])}",
            )
        else:
            # Default: local chat
            decision = RoutingDecision(
                model=self.default_model,
                task_type="chat",
                provider="ollama",
                confidence=0.5,
                reason="No specific signals — using default local model",
            )

        self._log(task_text, decision)
        return decision

    def route_for_agent(self, agent_name: str) -> RoutingDecision:
        """Convenience: route based on agent name."""
        agent_to_task = {
            "jd_analyzer":       "extraction",
            "resume_analyzer":   "extraction",
            "claim_extractor":   "extraction",
            "evidence_verifier": "verification_simple",
            "comparator":        "comparison",
            "tradeoff":          "comparison",
        }
        hint = agent_to_task.get(agent_name)
        return self.route(agent_name, task_type_hint=hint)

    def get_routing_table(self) -> list[dict]:
        return [
            {
                "task":        e["task"],
                "model":       e["model"],
                "provider":    e["provider"],
                "description": e["description"],
            }
            for e in self._routing_table
        ]

    def get_recent_decisions(self, n: int = 10) -> list[dict]:
        return self._route_log[-n:]

    def _log(self, task_text: str, decision: RoutingDecision):
        self._route_log.append({
            "input_preview": task_text[:80],
            **decision.to_dict(),
        })
        if len(self._route_log) > 50:
            self._route_log = self._route_log[-50:]
        print(f"[Router] {decision.task_type} -> {decision.provider}/{decision.model} "
              f"(conf={decision.confidence:.1f}) -- {decision.reason}")
