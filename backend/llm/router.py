"""
Smart LLM Router — routes each task type to the optimal model.

Routing strategy (Windows + Ollama + Gemini):
  intent_parsing   → Ollama (fast local, low stakes)
  step_planning    → Ollama or Gemini Flash (depends on complexity)
  fix_agent        → Gemini Flash (needs creativity)
  vision_critic    → Gemini Flash Vision (best vision for price)
  replan           → Gemini Pro (hardest reasoning task)
  advisor          → Ollama (fast, runs after every step)

Supported providers: "ollama" | "gemini"
"""
import asyncio
import logging
from typing import Optional

from .base_client import LLMClient, LLMResponse
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_router_instance: Optional["LLMRouter"] = None


# Task types and their preferred tier
TASK_TIER: dict[str, str] = {
    "intent_parsing": "fast",    # Ollama — fast, low stakes
    "step_planning":  "smart",   # Gemini Flash — needs good JSON + reasoning
    "advisor":        "fast",    # Ollama — runs after every step, must be fast
    "fix_agent":      "smart",   # Gemini Flash — needs creativity to recover
    "replan":         "smart",   # Gemini Flash — hardest reasoning task
    "vision":         "vision",  # Gemini Flash with image input
    "meta_planning":  "smart",   # For complex goal decomposition
}


class LLMRouter:
    """
    Unified LLM interface with task-aware model routing.

    Config shape (model_config):
      provider:       "ollama" | "gemini" | "api"
      model:          primary model name
      gemini_api_key: Google AI API key (for Gemini)
      gemini_model:   e.g. "gemini-2.0-flash"
      gemini_pro_model: e.g. "gemini-2.5-pro-preview"
      vision_model:   "gemini" | "ollama:llava" | "api:gpt-4o"
      base_url:       Ollama base URL
    """

    def __init__(self, config: dict):
        self._config  = config
        self._clients = self._build_clients(config)
        self.active_model = self._primary_model_name(config)

    def _build_clients(self, config: dict) -> dict[str, LLMClient]:
        mc      = config.get("model_config", {})
        timeout = mc.get("timeout_seconds", 60)
        clients = {}

        provider = mc.get("provider", "ollama")
        gemini_key = mc.get("gemini_api_key")

        # ── Fast client (intent parsing, advisor — runs MANY times per task) ──
        # Always try Ollama first for the fast tier, even when provider=gemini.
        # This avoids burning Gemini free-tier quota on high-frequency calls.
        ollama_url = mc.get("base_url", "http://localhost:11434")
        ollama_model = mc.get("model", "llama3")

        if provider == "ollama":
            clients["fast"] = OllamaClient(
                model=ollama_model,
                base_url=ollama_url,
                timeout=timeout,
            )
        elif provider == "gemini":
            # Try Ollama as fast tier to save Gemini quota
            ollama_available = False
            try:
                test_client = OllamaClient(model=ollama_model, base_url=ollama_url, timeout=5)
                ollama_available = test_client.test_connection()
            except Exception:
                pass

            if ollama_available:
                logger.info(f"Hybrid routing: Ollama ({ollama_model}) for fast tasks, Gemini for smart/vision")
                clients["fast"] = OllamaClient(
                    model=ollama_model,
                    base_url=ollama_url,
                    timeout=timeout,
                )
            else:
                from .gemini_client import GeminiClient
                logger.info("Ollama not available, using Gemini Flash for all tiers")
                clients["fast"] = GeminiClient(
                    api_key=gemini_key or "",
                    model="gemini-2.0-flash",
                    timeout=timeout,
                )
        else:
            raise ValueError(f"Unknown provider: {provider}. Supported: 'ollama', 'gemini'")

        # ── Smart client (planning, fix, replan — runs few times per task) ────
        # Only use Gemini for smart/vision tiers when the provider is "gemini".
        # If provider is "ollama", route ALL tiers through Ollama — respect
        # the user's explicit choice even if a leftover gemini_api_key exists.
        if provider == "gemini" and gemini_key:
            from .gemini_client import GeminiClient
            clients["smart"] = GeminiClient(
                api_key=gemini_key,
                model="gemini-2.0-flash",  # Flash for planning (fast + smart enough)
                timeout=timeout,
            )
            # Vision uses Flash — fast and excellent vision
            clients["vision"] = GeminiClient(
                api_key=gemini_key,
                model="gemini-2.0-flash",
                timeout=timeout,
            )
        else:
            # provider == "ollama" or no Gemini key → use Ollama for everything
            clients["smart"]  = clients["fast"]
            clients["vision"] = clients["fast"]

        return clients

    def _primary_model_name(self, config: dict) -> str:
        mc = config.get("model_config", {})
        provider = mc.get("provider", "ollama")
        if provider == "gemini":
            user_model = mc.get("gemini_model", "gemini-2.0-flash")
            if user_model != "gemini-2.0-flash":
                return f"flash + {user_model}"
            return "gemini-2.0-flash"
        return mc.get("model", "unknown")

    def reload(self, new_config: dict):
        self._config  = new_config
        self._clients = self._build_clients(new_config)
        self.active_model = self._primary_model_name(new_config)
        logger.info("LLM router reloaded.")

    def _client_for(self, task_type: str) -> LLMClient:
        tier = TASK_TIER.get(task_type, "fast")
        return self._clients.get(tier, self._clients["fast"])

    def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        task_type: str = "step_planning",    # ← pass this for smart routing
        timeout: float = 90.0,               # hard wall-clock timeout (seconds)
    ) -> str:
        """
        Synchronous wrapper — safe to call from a thread.
        Internally runs the LLM call in the current thread and honours timeout.
        NOTE: Do NOT call this directly from an async function — use
        agenerate_response() or wrap with asyncio.to_thread().
        """
        import concurrent.futures
        client = self._client_for(task_type)
        logger.debug(f"[Router] task={task_type} → {type(client).__name__}")

        def _call():
            return client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"LLM call timed out after {timeout}s (task={task_type})")
        return result.content

    async def agenerate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        task_type: str = "step_planning",
        timeout: float = 90.0,
    ) -> str:
        """
        Async-safe LLM call. Runs the blocking client.generate in a thread
        and enforces a hard asyncio timeout so the event loop is never blocked.
        """
        client = self._client_for(task_type)
        logger.debug(f"[Router] async task={task_type} → {type(client).__name__}")
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    client.generate,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"LLM call timed out after {timeout}s (task={task_type})")
        return result.content

    def generate_vision(
        self,
        prompt: str,
        screenshot_b64: str,
        before_b64: Optional[str] = None,
    ) -> str:
        """
        Vision call — routes to Gemini Flash vision if configured,
        otherwise falls back to standard vision model config.
        """
        vision_client = self._clients.get("vision")
        from .gemini_client import GeminiClient
        if isinstance(vision_client, GeminiClient):
            return vision_client.generate_with_vision(
                prompt=prompt,
                screenshot_b64=screenshot_b64,
                before_b64=before_b64,
            )
        # Fallback: pack into a standard generate call
        result = vision_client.generate(
            prompt=prompt,
            system_prompt=None,
            image_b64=screenshot_b64,
        )
        return result.content

    def test_connection(self) -> bool:
        return self._clients["fast"].test_connection()


def get_router() -> LLMRouter:
    global _router_instance
    if _router_instance is None:
        raise RuntimeError("LLMRouter not initialized. Call init_router() first.")
    return _router_instance


def init_router(config: dict) -> LLMRouter:
    global _router_instance
    _router_instance = LLMRouter(config)
    return _router_instance
