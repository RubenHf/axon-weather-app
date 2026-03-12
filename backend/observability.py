from collections.abc import Iterator
from contextlib import contextmanager
import logging
from typing import Any

from langfuse import get_client, propagate_attributes

from .settings import (
    get_langfuse_base_url,
    get_langfuse_public_key,
    get_langfuse_secret_key,
)

logger = logging.getLogger(__name__)

_missing_credentials_logged = False
_partial_config_logged = False


class NoopObservation:
    trace_id: str | None = None
    id: str | None = None

    def update(self, **_: Any) -> None:
        return


def _langfuse_is_configured() -> bool:
    global _partial_config_logged
    public_key = get_langfuse_public_key()
    secret_key = get_langfuse_secret_key()
    base_url = get_langfuse_base_url()
    has_keys = bool(public_key and secret_key)
    has_partial_config = bool(public_key or secret_key or base_url)
    if has_partial_config and not has_keys and not _partial_config_logged:
        logger.warning("Partial Langfuse config detected; tracing is disabled until both keys are set")
        _partial_config_logged = True
    return has_keys


def get_langfuse_client():
    global _missing_credentials_logged
    if not _langfuse_is_configured():
        if not _missing_credentials_logged:
            logger.info("Langfuse keys are not configured; running without tracing")
            _missing_credentials_logged = True
        return None
    return get_client()


@contextmanager
def start_observation(
    *,
    name: str,
    as_type: str = "span",
    input: Any = None,
    output: Any = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
) -> Iterator[Any]:
    client = get_langfuse_client()
    if client is None:
        yield NoopObservation()
        return

    kwargs: dict[str, Any] = {
        "name": name,
        "as_type": as_type,
    }
    if input is not None:
        kwargs["input"] = input
    if output is not None:
        kwargs["output"] = output
    if metadata is not None:
        kwargs["metadata"] = metadata
    if model is not None:
        kwargs["model"] = model

    with client.start_as_current_observation(**kwargs) as observation:
        yield observation


@contextmanager
def with_trace_attributes(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace_name: str | None = None,
) -> Iterator[None]:
    client = get_langfuse_client()
    if client is None:
        yield
        return

    kwargs: dict[str, Any] = {}
    if user_id is not None:
        kwargs["user_id"] = user_id
    if session_id is not None:
        kwargs["session_id"] = session_id
    if tags is not None:
        kwargs["tags"] = tags
    if metadata is not None:
        kwargs["metadata"] = metadata
    if trace_name is not None:
        kwargs["trace_name"] = trace_name

    with propagate_attributes(**kwargs):
        yield


def shutdown_observability() -> None:
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:
        logger.exception("Failed to shutdown Langfuse client cleanly")
