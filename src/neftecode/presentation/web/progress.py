from dataclasses import dataclass
import json
import queue
import threading
import time
from typing import Callable, Iterator

from neftecode.application.progress import reporting_to
from neftecode.application.cancellation import CancellationToken, cancellation_with

PHASE_LABELS = {
    "accepted": ("Запрос принят", "Условия разобраны сервером"),
    "scenario": ("Сценарий загружен", "Файл сценария прочитан и проверен загрузчиком"),
    "solving": ("Ядро решения считает", "Перебор планов, жёсткие проверки и работа агентов — этапы ниже отмечаются по мере готовности"),
    "ready": ("Решение готово", "Payload собран и отдан на экран"),
}

SENTINEL = object()


@dataclass
class Frame:
    event: str
    data: dict

    def encode(self) -> bytes:
        body = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {body}\n\n".encode("utf-8")


def _phase(key: str, state: str, elapsed_ms: int) -> Frame:
    label, detail = PHASE_LABELS.get(key, (key, ""))
    return Frame("phase", {"key": key, "label": label, "detail": detail, "state": state,
                           "elapsed_ms": elapsed_ms})


def decision_stream(compute: Callable[[], dict], heartbeat_s: float = 1.0) -> Iterator[Frame]:
    started = time.monotonic()
    cancellation = CancellationToken()
    channel: queue.Queue = queue.Queue()
    box: dict = {}

    def elapsed() -> int:
        return round((time.monotonic() - started) * 1000)

    def work() -> None:
        try:
            with cancellation_with(cancellation):
                with reporting_to(channel.put):
                    box["payload"] = compute()
        except BaseException as exc:
            box["error"] = exc
        finally:
            channel.put(SENTINEL)

    worker = None
    try:
        yield _phase("accepted", "done", elapsed())
        worker = threading.Thread(target=work, name="decision-stream", daemon=True)
        worker.start()

        while True:
            try:
                item = channel.get(timeout=heartbeat_s)
            except queue.Empty:
                yield Frame("tick", {"elapsed_ms": elapsed()})
                continue
            if item is SENTINEL:
                break
            yield _relay(item, elapsed())

        if "error" in box:
            yield Frame("failed", {"message": str(box["error"]), "elapsed_ms": elapsed()})
            return

        yield _phase("ready", "done", elapsed())
        yield Frame("screen", {"payload": box["payload"], "elapsed_ms": elapsed()})
        yield Frame("end", {"elapsed_ms": elapsed()})
    finally:
        cancellation.cancel()


def _relay(item: dict, elapsed_ms: int) -> Frame:
    kind = item.get("kind")
    if kind == "phase":
        return _phase(item.get("key", ""), item.get("state", "done"), elapsed_ms)
    if kind == "agent":
        return Frame("agent", {"event": item.get("event", {}), "elapsed_ms": elapsed_ms})
    if kind == "stage":
        data = {key: value for key, value in item.items() if key != "kind"}
        data["elapsed_ms"] = elapsed_ms
        return Frame("stage", data)
    return Frame("tick", {"elapsed_ms": elapsed_ms})
