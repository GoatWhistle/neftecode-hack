import threading
from typing import Callable


class DecisionCache:

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict = {}

    def get(self, key, compute: Callable[[], dict]) -> dict:
        with self._lock:
            entry = self._entries.get(key)
            owner = entry is None
            if owner:
                entry = self._entries[key] = {"done": threading.Event(), "payload": None, "error": None}
        if owner:
            try:
                entry["payload"] = compute()
            except BaseException as exc:
                entry["error"] = exc
                with self._lock:
                    self._entries.pop(key, None)
            finally:
                entry["done"].set()
        else:
            entry["done"].wait()
        if entry["error"] is not None:
            raise entry["error"]
        return entry["payload"]

    def put(self, key, payload: dict) -> None:
        entry = {"done": threading.Event(), "payload": payload, "error": None}
        entry["done"].set()
        with self._lock:
            self._entries[key] = entry

    def __len__(self) -> int:
        return len(self._entries)


def cache_key(canonical: dict) -> tuple:
    return tuple(sorted(canonical.items()))
