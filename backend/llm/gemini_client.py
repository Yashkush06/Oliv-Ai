"""
Google Gemini client — supports text generation and vision assessment.
Uses the official google-generativeai SDK.

Install: pip install google-generativeai
"""
import base64
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from .base_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    """
    Client for Google Gemini models via the generativeai SDK.

    Supports:
    - gemini-2.0-flash-lite  (fastest, cheapest — use for intent parsing)
    - gemini-2.0-flash       (balanced — use for planning, criticism)
    - gemini-2.5-pro-preview (strongest reasoning — use for replanning)

    Vision: pass image_b64 + mime_type to generate() for multimodal calls.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", timeout: float = 60.0):
        self.api_key   = api_key
        self.model     = model
        self.timeout   = timeout
        self._client   = self._build_client()

    def _build_client(self):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        return genai.GenerativeModel(self.model)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30), reraise=True)
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        image_b64: Optional[str] = None,
        mime_type: str = "image/jpeg",
    ) -> LLMResponse:
        import google.generativeai as genai

        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        # Build the content parts
        parts = []
        if system_prompt:
            # Gemini doesn't have a system role in basic API — prepend it
            parts.append(f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{prompt}")
        else:
            parts.append(prompt)

        if image_b64:
            import google.generativeai as genai
            img_data = base64.b64decode(image_b64)
            parts.append({"mime_type": mime_type, "data": img_data})

        response = self._client.generate_content(
            parts,
            generation_config=generation_config,
        )
        content = response.text
        return LLMResponse(content=content, model=self.model, provider="gemini")

    async def agenerate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        image_b64: Optional[str] = None,
        mime_type: str = "image/jpeg",
    ) -> LLMResponse:
        import google.generativeai as genai
        import asyncio

        # Run in thread since the SDK's async support is limited
        return await asyncio.to_thread(
            self.generate,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            image_b64=image_b64,
            mime_type=mime_type,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30), reraise=True)
    def generate_with_vision(
        self,
        prompt: str,
        screenshot_b64: str,
        before_b64: Optional[str] = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        """
        Dedicated vision call: pass 1 or 2 screenshots and a prompt.
        Used by the Critic and Reflector for visual verification.
        Returns raw text (caller parses JSON).
        """
        import google.generativeai as genai

        img_bytes = base64.b64decode(screenshot_b64)
        parts = [prompt, {"mime_type": mime_type, "data": img_bytes}]

        if before_b64:
            before_bytes = base64.b64decode(before_b64)
            # Insert before-image first so model sees: prompt → before → after
            parts = [
                prompt,
                {"mime_type": mime_type, "data": before_bytes},
                {"mime_type": mime_type, "data": img_bytes},
            ]

        response = self._client.generate_content(parts)
        return response.text.strip()

    def test_connection(self) -> bool:
        try:
            result = self.generate("Reply with: OK", max_tokens=10)
            return bool(result.content)
        except Exception as e:
            logger.warning(f"Gemini connection test failed: {e}")
            return False
