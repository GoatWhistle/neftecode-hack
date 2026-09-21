from contextlib import contextmanager
import threading
from typing import Iterator


class CancellationError(Exception):
    pass


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise CancellationError("Расчёт отменён клиентом")


_local = threading.local()


def check_cancelled() -> None:
    token = getattr(_local, "token", None)
    if token is not None:
        token.check()


@contextmanager
def cancellation_with(token: CancellationToken) -> Iterator[None]:
    previous = getattr(_local, "token", None)
    _local.token = token
    try:
        token.check()
        yield
    finally:
        _local.token = previous
