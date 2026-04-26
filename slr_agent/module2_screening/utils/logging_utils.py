"""
Logging utilities for SSE emission and message formatting.
"""

from typing import Optional, Callable


def emit_log(emitLog: Optional[Callable], message: str, count: int = 0) -> None:
    """
    Null-safe SSE emitter wrapper. Tolerates both 2-arg and 3-arg signatures.
    """
    if emitLog:
        try:
            emitLog("screen", message, count)
        except TypeError:
            emitLog("screen", message)


# Aliases for backward compatibility
_emitLog = emit_log


def log_message(emitLog: Optional[Callable], message: str, count: int = 0) -> None:
    """Legacy log wrapper."""
    if emitLog:
        try:
            emitLog("screen", message, count)
        except TypeError:
            emitLog("screen", message)


_log = log_message