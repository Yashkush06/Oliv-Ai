import json
import logging
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .base_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    """Client for locally running Ollama models."""

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: float = 60.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            return LLMResponse(content=content, model=self.model, provider="ollama")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    async def agenerate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            return LLMResponse(content=content, model=self.model, provider="ollama")

    def test_connection(self) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama connection test failed: {e}")
            return False

    @staticmethod
    def list_models(base_url: str = "http://localhost:11434") -> list[str]:
        """Return names of all locally installed Ollama models."""
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{base_url.rstrip('/')}/api/tags")
                response.raise_for_status()
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []
