from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tokens_used: Optional[int] = None


class LLMClient(ABC):
    """Abstract base class for all LLM provider clients."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response synchronously."""
        ...

    @abstractmethod
    async def agenerate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response asynchronously."""
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Verify the client can reach its endpoint."""
        ...
