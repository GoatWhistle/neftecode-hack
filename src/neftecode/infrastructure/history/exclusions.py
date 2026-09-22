import hashlib
import json
from pathlib import Path

from neftecode.application.history.prepare import HistoryError, local_moment

MAX_EXCLUSIONS = 100


class ExclusionRegistry:
    def __init__(self, path: Path):
        self.items = []
        self.provenance = {"path": "research/data/excluded-periods.json", "available": path.is_file()}
        if not path.is_file():
            return
        raw = path.read_bytes()
        data = json.loads(raw)
        self.provenance.update(sha256=hashlib.sha256(raw).hexdigest(), generated_at=data.get("generated_at"))
        for key, scope in (("dead_columns_excluded_entirely", "column"),
                           ("stub_row_bursts", "telemetry"), ("pak_frozen_intervals", "pak"),
                           ("pak_lab_conflict_events", "pak_lab_sample")):
            for item in data.get(key, []):
                start = item.get("from") or item.get("data_from") or item["at"]
                end = item.get("to") or item.get("data_to") or start
                self.items.append({"start": start, "end": end, "scope": scope, "reason": item["reason"],
                                   "column": item.get("column"), "blocks_decision": False})
        self.items.sort(key=lambda item: (item["start"], item["scope"]))

    def between(self, start: str, end: str, offset: int = 0, limit: int = 50) -> dict:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_EXCLUSIONS:
            raise HistoryError("invalid_budget", "Реестр: offset ≥ 0, limit от 1 до 100")
        first, last = local_moment(start), local_moment(end)
        if first > last:
            raise HistoryError("invalid_period", "Начало периода позже конца")
        found = [item for item in self.items
                 if local_moment(item["start"]) <= last and local_moment(item["end"]) >= first]
        stop = offset + limit
        return {"items": found[offset:stop], "total": len(found),
                "next_offset": stop if stop < len(found) else None, "provenance": self.provenance,
                "note": "Реестр исключений источников. Пригодность решения проверяется отдельно на выбранный момент."}
