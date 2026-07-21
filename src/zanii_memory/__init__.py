"""ZaniiDB Agent Memory — layered long-term memory (L0→L3) for AI agents."""

__version__ = "0.9.0"

from .config import Settings
from .core import MemoryCore, ZaniiMemory
from .types import MemoryRecord, RecallResult

__all__ = ["ZaniiMemory", "MemoryCore", "Settings", "MemoryRecord", "RecallResult", "__version__"]
