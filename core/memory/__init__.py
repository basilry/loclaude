"""Memory backend abstraction layer."""

from core.memory.base import MemoryBackend
from core.memory.factory import create_memory_backend

__all__ = ["MemoryBackend", "create_memory_backend"]
