"""Engine abstraction layer."""

from core.engines.base import EngineProtocol
from core.engines.factory import create_engine

__all__ = ["EngineProtocol", "create_engine"]
