"""Model candidates and fallback matrix for benchmarking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelCandidate:
    provider: str  # "mlx", "openai", "openai-compat"
    model: str
    base_url: str
    description: str
    api_key_env: str | None = None


@dataclass
class ModelMatrix:
    candidates: list[ModelCandidate] = field(default_factory=list)

    @classmethod
    def default(cls) -> ModelMatrix:
        """기본 벤치마크 후보 모델 목록."""
        return cls(
            candidates=[
                ModelCandidate(
                    provider="mlx",
                    model="mlx-community/Qwen3-30B-A3B-4bit",
                    base_url="http://localhost:8080/v1",
                    description="MLX Qwen3-30B-A3B MoE 4bit (local, Apple Silicon)",
                ),
                ModelCandidate(
                    provider="openai",
                    model="gpt-4o-mini",
                    base_url="https://api.openai.com/v1",
                    description="OpenAI gpt-4o-mini (cloud, low cost)",
                    api_key_env="OPENAI_API_KEY",
                ),
                ModelCandidate(
                    provider="openai-compat",
                    model="qwen3:30b-a3b",
                    base_url="http://localhost:11434/v1",
                    description="Ollama Qwen3-30B-A3B via OpenAI compat",
                ),
            ]
        )

    def filter_by_provider(self, provider: str) -> list[ModelCandidate]:
        return [c for c in self.candidates if c.provider == provider]

    def add(self, candidate: ModelCandidate) -> None:
        self.candidates.append(candidate)
