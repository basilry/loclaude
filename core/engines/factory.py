"""엔진 팩토리. provider 문자열로 적절한 엔진 인스턴스 생성."""

from __future__ import annotations

from core.engines.base import EngineProtocol


def create_engine(
    provider: str,
    model: str,
    base_url: str,
    api_key: str | None = None,
) -> EngineProtocol:
    """provider 문자열에 따라 엔진 인스턴스를 생성한다.

    provider: "mlx", "openai", "openai-compat"
    """
    if provider == "mlx":
        from core.engines.mlx import MLXEngine
        return MLXEngine(model=model, base_url=base_url)

    if provider == "openai":
        from core.engines.openai_responses import OpenAIResponsesEngine
        return OpenAIResponsesEngine(model=model, base_url=base_url, api_key=api_key)

    if provider == "openai-compat":
        from core.engines.openai_compat import OpenAICompatEngine
        return OpenAICompatEngine(model=model, base_url=base_url, api_key=api_key)

    raise ValueError(f"Unknown provider: {provider!r}. Use 'mlx', 'openai', or 'openai-compat'.")
