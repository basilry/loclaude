"""호환용 re-export. 실제 구현은 core/engines/mlx.py로 이동."""

from core.engines.mlx import MLXEngine

__all__ = ["MLXEngine"]
