from contextlib import contextmanager
from typing import Callable, Iterator
import threading

_local = threading.local()


def current_sink() -> Callable[[dict], None] | None:
    return getattr(_local, "sink", None)


def emit(kind: str, **values) -> None:
    sink = current_sink()
    if sink is not None:
        sink({"kind": kind, **values})


def emit_agent_event(event: dict) -> None:
    sink = current_sink()
    if sink is not None:
        sink({"kind": "agent", "event": event})


@contextmanager
def reporting_to(sink: Callable[[dict], None] | None) -> Iterator[None]:
    previous = getattr(_local, "sink", None)
    _local.sink = sink
    try:
        yield
    finally:
        _local.sink = previous
