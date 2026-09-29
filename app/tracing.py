from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def start_as_current_observation(self, **kwargs: Any):
            @contextmanager
            def _observation():
                yield None

            return _observation()

        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

        def get_current_trace_id(self) -> str | None:
            return None

        def flush(self) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client()


@contextmanager
def start_observation(
    *, name: str, as_type: str = "span", **kwargs: Any
) -> Iterator[Any | None]:
    """Create a nested Langfuse observation when the SDK exposes the v4 API.

    The no-op path keeps the application runnable without Langfuse credentials and
    also makes unit tests independent from the external service.
    """

    client = get_langfuse_client()
    starter = getattr(client, "start_as_current_observation", None)
    if not callable(starter):
        yield None
        return

    with starter(name=name, as_type=as_type, **kwargs) as observation:
        yield observation


def update_observation(observation: Any | None, **kwargs: Any) -> None:
    if observation is None:
        return
    updater = getattr(observation, "update", None)
    if callable(updater):
        updater(**kwargs)


def get_current_trace_id(client: Any | None = None) -> str | None:
    client = client or get_langfuse_client()
    getter = getattr(client, "get_current_trace_id", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:  # pragma: no cover - defensive SDK compatibility fallback
        return None


def flush_traces(client: Any | None = None) -> None:
    client = client or get_langfuse_client()
    flusher = getattr(client, "flush", None)
    if callable(flusher):
        flusher()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
