from .llm_client import LLMClient
from .logger import DecisionLogger
from .prisma_manager import PRISMAManager


def __getattr__(name: str):  # type: ignore[return]
    """Lazy-load heavy modules (encoder, storage) only when accessed."""
    if name == "SharedEncoderService":
        from .encoder import SharedEncoderService
        return SharedEncoderService
    if name == "VersionedStorage":
        from .storage import VersionedStorage
        return VersionedStorage
    raise AttributeError(f"module 'infrastructure' has no attribute {name!r}")
