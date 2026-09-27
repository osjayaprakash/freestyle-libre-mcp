"""Optional Langfuse tracing.

Every entry point is a passthrough until `configure()` installs a Langfuse
client. Errors are recorded by hand instead of via Langfuse's `@observe`,
which always writes `str(exception)` into the trace; our error messages can
contain patient names, which must stay out of traces unless capture is on.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, ParamSpec, TypeVar

from librelinkup_mcp.config import Settings

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_client: Any | None = None
_capture = False


def configure(settings: Settings, *, client: Any | None = None) -> None:
    """Enable tracing when settings allow it. `client` overrides the Langfuse client (tests)."""
    global _client, _capture
    _client = None
    _capture = settings.langfuse_capture_data
    if not settings.langfuse_enabled:
        return
    if client is None:
        try:
            from langfuse import get_client
        except ImportError:
            log.warning(
                "LANGFUSE_* keys are set but the 'langfuse' package is not installed; "
                "tracing is disabled. Install with: pip install 'librelinkup-mcp[langfuse]'"
            )
            return
        client = get_client()
    _client = client


def shutdown() -> None:
    """Flush pending traces. Safe to call when tracing is disabled."""
    if _client is not None:
        _client.shutdown()


def _discard(_value: Any) -> None:
    pass


@asynccontextmanager
async def _observe(
    name: str, as_type: str, *, input: Any = None, metadata: dict[str, Any] | None = None
) -> AsyncIterator[Callable[[Any], None]]:
    """Open an observation; yields a callback that records the output."""
    if _client is None:
        yield _discard
        return

    error: Exception | None = None
    with _client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input if _capture else None,
        metadata=metadata,
    ) as observation:

        def record_output(value: Any) -> None:
            if _capture:
                observation.update(output=value)

        try:
            yield record_output
        except Exception as exc:
            error = exc
            observation.update(
                level="ERROR",
                status_message=str(exc) if _capture else type(exc).__name__,
            )
    if error is not None:
        raise error


def span(name: str, metadata: dict[str, Any] | None = None):
    """Async context manager for a child span, e.g. one upstream API call."""
    return _observe(name, "span", metadata=metadata)


def traced(name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async MCP tool so each call becomes one Langfuse observation."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            async with _observe(
                name, "tool", input=dict(kwargs), metadata={"tool": name}
            ) as record_output:
                result = await func(*args, **kwargs)
                record_output(result)
            return result

        return wrapper

    return decorator
