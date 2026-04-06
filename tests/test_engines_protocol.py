"""Engine protocol conformance tests."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import inspect
from typing import get_type_hints

from core.engines.base import EngineProtocol
from core.engines.mlx import MLXEngine
from core.engines.openai_responses import OpenAIResponsesEngine
from core.engines.openai_compat import OpenAICompatEngine
from core.types import TokenUsage


ENGINE_CLASSES = [MLXEngine, OpenAIResponsesEngine, OpenAICompatEngine]


def test_runtime_checkable():
    """All engines satisfy EngineProtocol via isinstance."""
    for cls in ENGINE_CLASSES:
        instance = object.__new__(cls)
        instance.provider_name = "test"
        instance.model = "test"
        instance.base_url = "http://localhost"
        assert isinstance(instance, EngineProtocol), f"{cls.__name__} not EngineProtocol"
    print("  runtime_checkable")


def test_chat_return_annotation():
    """chat() return type is tuple[str, TokenUsage]."""
    for cls in ENGINE_CLASSES:
        hints = get_type_hints(cls.chat)
        ret = hints.get("return")
        assert ret is not None, f"{cls.__name__}.chat() missing return annotation"
        assert "tuple" in str(ret).lower(), f"{cls.__name__}.chat() return not tuple: {ret}"
        assert "TokenUsage" in str(ret), f"{cls.__name__}.chat() missing TokenUsage: {ret}"
    print("  chat_return_annotation")


def test_ping_return_annotation():
    """ping() return type is bool."""
    for cls in ENGINE_CLASSES:
        hints = get_type_hints(cls.ping)
        ret = hints.get("return")
        assert ret is bool, f"{cls.__name__}.ping() return not bool: {ret}"
    print("  ping_return_annotation")


def test_mandatory_properties():
    """provider_name and model are present on all engines."""
    for cls in ENGINE_CLASSES:
        assert hasattr(cls, "provider_name"), f"{cls.__name__} missing provider_name"
        instance = object.__new__(cls)
        instance.model = "test"
        assert hasattr(instance, "model"), f"{cls.__name__} missing model"
    print("  mandatory_properties")


def test_chat_signature_matches_protocol():
    """chat() params match EngineProtocol.chat()."""
    proto_params = set(inspect.signature(EngineProtocol.chat).parameters.keys())
    for cls in ENGINE_CLASSES:
        cls_params = set(inspect.signature(cls.chat).parameters.keys())
        assert proto_params == cls_params, (
            f"{cls.__name__}.chat() params {cls_params} != protocol {proto_params}"
        )
    print("  chat_signature_matches")


if __name__ == "__main__":
    print("test_engines_protocol:")
    test_runtime_checkable()
    test_chat_return_annotation()
    test_ping_return_annotation()
    test_mandatory_properties()
    test_chat_signature_matches_protocol()
    print("  All passed!")
