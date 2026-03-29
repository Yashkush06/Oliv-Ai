"""
API client for cloud/proxy-based LLMs (OpenAI-compatible + Anthropic).

Key design decisions:
- Uses httpx directly for full control over timeouts and headers
- Hard per-request timeout (default: 60s) — never hangs the agent event loop
- Fast-fail on 401/unauthorized errors — no retry storms on bad API keys
- Injects spoof headers for restrictive proxy gateways (e.g. AgentRouter)
- Tenacity retry ONLY applies to transient server errors (5xx / timeout)
"""
import json
import logging
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

# Headers that make certain proxy gateways (AgentRouter etc.) accept requests
_PROXY_SPOOF_HEADERS = {
    "User-Agent": "codex_cli_rs/0.101.0",
    "Originator": "codex_cli_rs",
    "Version": "0.101.0",
}


class APIAuthError(Exception):
    """Raised immediately on 401/403 — must NOT be retried."""


class APIServerError(Exception):
    """Raised on 5xx — eligible for retry."""


def _raise_for_status(status_code: int, body: str, url: str) -> None:
    if status_code in (401, 403):
        # Try to extract message from JSON
        try:
            msg = json.loads(body).get("error", {}).get("message", body[:200])
        except Exception:
            msg = body[:200]
        raise APIAuthError(f"Auth error {status_code} from {url}: {msg}")
    if status_code >= 500:
        raise APIServerError(f"Server error {status_code} from {url}: {body[:200]}")
    if status_code >= 400:
        try:
            msg = json.loads(body).get("error", {}).get("message", body[:200])
        except Exception:
            msg = body[:200]
        raise RuntimeError(f"Client error {status_code} from {url}: {msg}")


class APIClient(LLMClient):
    """Client for cloud-based model APIs: OpenAI-compatible or Anthropic."""

    def __init__(
        self,
        api_provider: str,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.api_provider = api_provider.lower()
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._base_url = base_url
        # Pre-build the openai client for sync calls (anthropic handled inline)
        self._openai_client = self._build_openai_client() if self.api_provider != "anthropic" else None

    # ── Client builders ───────────────────────────────────────────────────────

    def _build_openai_client(self):
        import openai
        kwargs = {
            "api_key": self.api_key,
            "timeout": self.timeout,
            "default_headers": dict(_PROXY_SPOOF_HEADERS),
        }
        if self.api_provider == "groq":
            kwargs["base_url"] = "https://api.groq.com/openai/v1"
        elif self._base_url:
            kwargs["base_url"] = self._base_url
        return openai.OpenAI(**kwargs)

    def _build_async_openai_client(self):
        import openai
        kwargs = {
            "api_key": self.api_key,
            "timeout": self.timeout,
            "default_headers": dict(_PROXY_SPOOF_HEADERS),
        }
        if self.api_provider == "groq":
            kwargs["base_url"] = "https://api.groq.com/openai/v1"
        elif self._base_url:
            kwargs["base_url"] = self._base_url
        return openai.AsyncOpenAI(**kwargs)

    # ── Sync generation ───────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(APIServerError),   # only retry 5xx
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        image_b64: Optional[str] = None,
    ) -> LLMResponse:
        if self.api_provider == "anthropic":
            return self._generate_anthropic(prompt, system_prompt, temperature, max_tokens, image_b64)
        return self._generate_openai(prompt, system_prompt, temperature, max_tokens, image_b64)

    def _generate_openai(self, prompt, system_prompt, temperature, max_tokens, image_b64) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            })
        else:
            messages.append({"role": "user", "content": prompt})

        try:
            response = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            # Convert openai status errors to our typed exceptions so retry logic works
            self._handle_openai_exception(e)
            raise  # unreachable but keeps type checker happy

        content = response.choices[0].message.content
        return LLMResponse(content=content, model=self.model, provider=self.api_provider)

    def _generate_anthropic(self, prompt, system_prompt, temperature, max_tokens, image_b64) -> LLMResponse:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        messages = []
        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            })
        else:
            messages.append({"role": "user", "content": prompt})

        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt or "You are a helpful assistant.",
            messages=messages,
        )
        content = response.content[0].text
        return LLMResponse(content=content, model=self.model, provider="anthropic")

    # ── Async generation ──────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(APIServerError),
        reraise=True,
    )
    async def agenerate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        image_b64: Optional[str] = None,
    ) -> LLMResponse:
        if self.api_provider == "anthropic":
            return await self._agenerate_anthropic(prompt, system_prompt, temperature, max_tokens, image_b64)
        return await self._agenerate_openai(prompt, system_prompt, temperature, max_tokens, image_b64)

    async def _agenerate_openai(self, prompt, system_prompt, temperature, max_tokens, image_b64) -> LLMResponse:
        async_client = self._build_async_openai_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            })
        else:
            messages.append({"role": "user", "content": prompt})

        try:
            response = await async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            self._handle_openai_exception(e)
            raise

        content = response.choices[0].message.content
        return LLMResponse(content=content, model=self.model, provider=self.api_provider)

    async def _agenerate_anthropic(self, prompt, system_prompt, temperature, max_tokens, image_b64) -> LLMResponse:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
        messages = []
        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            })
        else:
            messages.append({"role": "user", "content": prompt})
        response = await client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt or "You are a helpful assistant.",
            messages=messages,
        )
        content = response.content[0].text
        return LLMResponse(content=content, model=self.model, provider="anthropic")

    # ── Error translation ─────────────────────────────────────────────────────

    @staticmethod
    def _handle_openai_exception(exc: Exception) -> None:
        """Translate openai SDK exceptions to our typed exception hierarchy."""
        try:
            import openai
            if isinstance(exc, openai.AuthenticationError):
                raise APIAuthError(str(exc)) from exc
            if isinstance(exc, openai.PermissionDeniedError):
                raise APIAuthError(str(exc)) from exc
            if isinstance(exc, openai.InternalServerError):
                raise APIServerError(str(exc)) from exc
            # AgentRouter returns 400 BadRequestError with type=unauthorized_client_error
            if isinstance(exc, openai.BadRequestError):
                body = getattr(exc, "body", None) or {}
                if isinstance(body, str):
                    try:
                        import json as _json
                        body = _json.loads(body)
                    except Exception:
                        body = {}
                err_type = body.get("type", "") or (body.get("error") or {}).get("type", "")
                if "unauthorized" in err_type.lower() or "unauthorized" in str(exc).lower():
                    raise APIAuthError(
                        f"Proxy rejected client as unauthorized (type={err_type}). "
                        "Check your API key or contact the proxy provider. "
                        f"Detail: {exc}"
                    ) from exc
                raise RuntimeError(str(exc)) from exc
            if isinstance(exc, openai.APIStatusError):
                _raise_for_status(exc.status_code, exc.body or "", str(exc.request.url))
        except (APIAuthError, APIServerError, RuntimeError):
            raise
        except Exception:
            pass  # if translation fails, let original exception propagate


    # ── Connection test ───────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        try:
            result = self.generate("Reply with: OK", max_tokens=10)
            return bool(result.content)
        except APIAuthError as e:
            logger.error(f"API auth failure (check your API key / proxy): {e}")
            return False
        except Exception as e:
            logger.warning(f"API connection test failed: {e}")
            return False
