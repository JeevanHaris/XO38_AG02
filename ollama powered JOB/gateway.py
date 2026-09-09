"""
RecruitScreen v1.0 — Multi-Provider Model Gateway
──────────────────────────────────────────────────
Extends ARIA's ModelGateway with:
  - GroqGateway: cloud inference via Groq API
  - MultiGateway: delegates to Ollama or Groq based on provider param

Usage:
    from gateway import MultiGateway
    gateway = MultiGateway()
    response = gateway.call("qwen3:4b", messages, provider="ollama")
    response = gateway.call("llama-3.3-70b-versatile", messages, provider="groq")
"""

import os
import time
import ollama


# ─── Response Object ──────────────────────────────────────────────────
class GatewayResponse:
    """Structured response from any gateway call."""

    def __init__(self, content, model, tokens_in=0, tokens_out=0,
                 latency=0.0, done=True, provider="ollama"):
        self.content    = content
        self.model      = model
        self.tokens_in  = tokens_in
        self.tokens_out = tokens_out
        self.latency    = latency
        self.done       = done
        self.provider   = provider

    def to_dict(self):
        return {
            "content":  self.content,
            "model":    self.model,
            "provider": self.provider,
            "usage": {
                "input_tokens":  self.tokens_in,
                "output_tokens": self.tokens_out,
            },
            "latency":    round(self.latency, 2),
            "stop_reason": "stop" if self.done else None,
        }


class GatewayError(Exception):
    """General Gateway failure."""
    pass


class GroqNetworkError(GatewayError):
    """Raised when Groq is reachable but all transient-retry attempts fail (network instability)."""
    pass


class ModelNotFoundError(Exception):
    """Raised when a requested model is not available."""
    def __init__(self, model, provider="ollama"):
        self.model    = model
        self.provider = provider
        super().__init__(
            f"Model '{model}' not found on {provider}. "
            f"Run: ollama pull {model}" if provider == "ollama" else
            f"Check your Groq model name."
        )


# ─── Ollama Gateway ───────────────────────────────────────────────────
class ModelGateway:
    """Unified interface for Ollama model calls with VRAM management."""

    def __init__(self, default_model=None, keep_alive="5m"):
        self.default_model  = default_model or os.environ.get("LOCAL_MODEL", "llama3.2:latest")
        self.keep_alive     = keep_alive
        self._last_model    = None
        self._call_count    = 0
        self._total_latency = 0.0

    def call(self, model_id, messages, **kwargs):
        model = model_id or self.default_model
        ka    = kwargs.pop("keep_alive", self.keep_alive)

        if self._last_model and self._last_model != model:
            print(f"[OllamaGateway] Model switch: {self._last_model} -> {model}")
        self._last_model = model

        t0 = time.time()
        try:
            response = ollama.chat(
                model=model,
                messages=messages,
                keep_alive=ka,
                **kwargs,
            )
            latency = time.time() - t0
            self._call_count    += 1
            self._total_latency += latency

            reply      = response.message.content
            tokens_in  = response.prompt_eval_count or 0
            tokens_out = response.eval_count or 0

            print(f"[OllamaGateway] {model} -- {latency:.1f}s -- "
                  f"{tokens_in}->{tokens_out} tokens")

            return GatewayResponse(
                content=reply, model=model,
                tokens_in=tokens_in, tokens_out=tokens_out,
                latency=latency, done=response.done,
                provider="ollama",
            )

        except ollama.ResponseError as e:
            if "not found" in str(e).lower():
                if model != self.default_model:
                    print(f"[OllamaGateway] Model '{model}' not found, "
                          f"falling back to {self.default_model}")
                    return self.call(self.default_model, messages, keep_alive=ka)
                raise ModelNotFoundError(model, "ollama") from e
            raise GatewayError(f"Ollama error: {e}") from e
        except Exception as e:
            raise GatewayError(f"Ollama Gateway error: {e}") from e

    def is_available(self):
        try:
            ollama.list()
            return True
        except Exception:
            return False

    def list_available(self):
        try:
            result = ollama.list()
            return [m.model for m in result.models]
        except Exception:
            return []

    def warm_up(self, model_id=None):
        model = model_id or self.default_model
        try:
            print(f"[OllamaGateway] Warming up {model}...")
            self.call(model, [{"role": "user", "content": "hi"}])
            print(f"[OllamaGateway] {model} ready.")
        except Exception as e:
            print(f"[OllamaGateway] Warm-up failed for {model}: {e}")

    def stats(self):
        return {
            "total_calls":   self._call_count,
            "total_latency": round(self._total_latency, 2),
            "avg_latency":   round(self._total_latency / max(self._call_count, 1), 2),
            "last_model":    self._last_model,
        }


# ─── Groq Gateway ─────────────────────────────────────────────────────
class GroqGateway:
    """Cloud inference via Groq API for complex reasoning tasks."""

    DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(self, api_key: str = None, default_model: str = None):
        self.api_key       = api_key or os.environ.get("GROQ_API_KEY", "")
        self.default_model = default_model or os.environ.get(
            "GROQ_MODEL", self.DEFAULT_MODEL
        )
        self._call_count    = 0
        self._total_latency = 0.0
        self._client        = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
                self._client = Groq(api_key=self.api_key)
            except ImportError:
                raise GatewayError(
                    "groq package not installed. Run: pip install groq"
                )
        return self._client

    def call(self, model_id, messages, max_retries: int = 3,
             timeout: int = 60, **kwargs):
        if not self.api_key:
            raise GatewayError(
                "GROQ_API_KEY not set. Add it to .env or set GROQ_API_KEY env var."
            )

        model  = model_id or self.default_model
        client = self._get_client()

        # Groq doesn't accept 'keep_alive' or other Ollama-specific kwargs
        kwargs.pop("keep_alive", None)

        # Transient network errors that should be retried
        _RETRYABLE = (
            "wsarecv", "connection reset", "remotedisconnected",
            "connectionreset", "broken pipe", "stream reading error",
            "connection aborted", "read timeout", "timed out",
        )

        last_exc = None
        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    timeout=timeout,
                    **kwargs,
                )
                latency = time.time() - t0
                self._call_count    += 1
                self._total_latency += latency

                reply      = completion.choices[0].message.content
                tokens_in  = completion.usage.prompt_tokens     if completion.usage else 0
                tokens_out = completion.usage.completion_tokens if completion.usage else 0

                print(f"[GroqGateway] {model} -- {latency:.1f}s -- "
                      f"{tokens_in}->{tokens_out} tokens"
                      + (f" (attempt {attempt})" if attempt > 1 else ""))

                return GatewayResponse(
                    content=reply, model=model,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                    latency=latency, done=True,
                    provider="groq",
                )

            except Exception as e:
                last_exc = e
                err_str  = str(e).lower()
                is_transient = any(sig in err_str for sig in _RETRYABLE)

                if is_transient and attempt < max_retries:
                    wait = 2 ** (attempt - 1)   # 1s, 2s, 4s …
                    print(f"[GroqGateway] ⚠ Transient network error "
                          f"(attempt {attempt}/{max_retries}), "
                          f"retrying in {wait}s: {e}")
                    time.sleep(wait)
                    continue

                # Non-retryable or exhausted retries
                if attempt > 1:
                    print(f"[GroqGateway] ✗ Failed after {attempt} attempts: {e}")
                if is_transient:
                    raise GroqNetworkError(f"Groq network error after {attempt} attempts: {e}") from e
                raise GatewayError(f"Groq API error: {e}") from e

        raise GroqNetworkError(f"Groq network error after {max_retries} retries: {last_exc}")

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            client = self._get_client()
            client.models.list()
            return True
        except Exception:
            return False

    def stats(self):
        return {
            "total_calls":   self._call_count,
            "total_latency": round(self._total_latency, 2),
            "avg_latency":   round(self._total_latency / max(self._call_count, 1), 2),
            "provider":      "groq",
        }


# ─── Multi-Provider Gateway ───────────────────────────────────────────
class MultiGateway:
    """
    Delegates calls to either Ollama or Groq based on:
      - Explicit `provider` kwarg
      - Task complexity signals from the Smart Router
    """

    def __init__(
        self,
        ollama_default_model: str = None,
        groq_api_key: str = None,
        groq_default_model: str = None,
    ):
        self.ollama = ModelGateway(default_model=ollama_default_model or os.environ.get("LOCAL_MODEL", "llama3.2:latest"))
        self.groq   = GroqGateway(api_key=groq_api_key,
                                  default_model=groq_default_model)
        self._groq_enabled = bool(
            groq_api_key or os.environ.get("GROQ_API_KEY")
        )

    def call(self, model_id: str, messages: list, provider: str = "ollama", **kwargs):
        """
        Call the appropriate gateway.

        Args:
            model_id:  Model name — Ollama name or Groq model name
            messages:  List of {role, content} dicts
            provider:  "ollama" | "groq"
            **kwargs:  Passed through to the underlying gateway

        Fallback: if Groq raises any GatewayError (including network failures after
        all retries), automatically falls back to local Ollama so the pipeline
        never crashes due to intermittent cloud connectivity.
        """
        if provider == "groq" and self._groq_enabled:
            try:
                return self.groq.call(model_id or self.groq.default_model,
                                      messages, **kwargs)
            except GatewayError as e:
                print(f"[MultiGateway] ⚠ Groq unavailable ({type(e).__name__}: {e}). "
                      f"Falling back to local Ollama ({self.ollama.default_model}).")
                # Fall through to Ollama
        return self.ollama.call(model_id or self.ollama.default_model,
                                messages, **kwargs)

    def is_available(self) -> bool:
        """At least one backend must be available."""
        return self.ollama.is_available()

    def list_available(self) -> list[str]:
        return self.ollama.list_available()

    def groq_available(self) -> bool:
        return self._groq_enabled and self.groq.is_available()

    def warm_up(self, model_id: str = None):
        self.ollama.warm_up(model_id)

    def stats(self) -> dict:
        return {
            "ollama": self.ollama.stats(),
            "groq":   self.groq.stats() if self._groq_enabled else None,
        }
