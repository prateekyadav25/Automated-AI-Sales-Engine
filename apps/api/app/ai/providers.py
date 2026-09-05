import json
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    is_mock: bool
    estimated_cost: float


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, *, system: str, model: str | None = None) -> CompletionResult:
        raise NotImplementedError


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    def complete(self, prompt: str, *, system: str, model: str | None = None) -> CompletionResult:
        started = time.perf_counter()
        snippet = prompt[:400].replace("\n", " ")
        text = (
            "[MOCK LLM] Grounded response using retrieved tools and knowledge only. "
            f"System={system[:80]}. Prompt excerpt: {snippet}"
        )
        if "email" in system.lower() or "draft" in prompt.lower():
            text = (
                "Subject: Follow-up from AGRAYIAN AI Labs\n\n"
                "Hello,\n\nBased on the account context provided by tools, I recommend a concise "
                "follow-up that restates the stated problem and proposes a 30-minute discovery. "
                "This draft is not sent.\n\nRegards,\nAGRAYIAN Revenue OS"
            )
        latency = int((time.perf_counter() - started) * 1000)
        return CompletionResult(
            text=text,
            provider="mock",
            model=model or "mock-llm",
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            latency_ms=latency,
            is_mock=True,
            estimated_cost=0.0,
        )


class MockEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 32
            for i, ch in enumerate(text.lower()):
                vec[i % 32] += (ord(ch) % 13) / 13.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class OpenAILLMProvider(LLMProvider):
    def complete(self, prompt: str, *, system: str, model: str | None = None) -> CompletionResult:
        from openai import OpenAI

        settings = get_settings()
        chosen = model or settings.openai_default_model or settings.openai_fast_model
        if not chosen:
            raise RuntimeError("OPENAI_DEFAULT_MODEL is not configured")
        client = OpenAI(api_key=settings.openai_api_key)
        started = time.perf_counter()
        response = client.responses.create(
            model=chosen,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = getattr(response, "output_text", None) or json.dumps(response.model_dump())
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        latency = int((time.perf_counter() - started) * 1000)
        return CompletionResult(
            text=text,
            provider="openai",
            model=chosen,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            latency_ms=latency,
            is_mock=False,
            estimated_cost=0.0,
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        settings = get_settings()
        model = settings.openai_embedding_model
        if not model:
            raise RuntimeError("OPENAI_EMBEDDING_MODEL is not configured")
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.resolved_llm_provider == "openai":
        return OpenAILLMProvider()
    return MockLLMProvider()


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.resolved_llm_provider == "openai" and settings.openai_embedding_model:
        return OpenAIEmbeddingProvider()
    return MockEmbeddingProvider()
