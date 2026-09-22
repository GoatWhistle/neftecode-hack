import math

from .time import local_moment

MAX_SNAPSHOTS = 100
FACT_KEYS = ("lab_value", "lab_sample_time", "lab_available_time", "pak_value", "pak_sample_time",
             "telemetry_missing_fraction")


def snapshot_id(snapshot: dict) -> str:
    when = local_moment(snapshot["at"])
    stamp = when.strftime("%Y%m%d-%H%M%S")
    if when.microsecond:
        stamp += f".{when.microsecond:06d}"
    return stamp + ("-synthetic" if snapshot.get("synthetic_edits") else "")


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def snapshot_item(snapshot: dict) -> dict:
    state = snapshot["state"]
    return {
        "snapshot": snapshot_id(snapshot), "at": snapshot["at"],
        "label": snapshot.get("label") or "Исторический срез",
        "synthetic_edits": list(snapshot.get("synthetic_edits") or []),
        "facts": {key: finite(state.get(key)) for key in FACT_KEYS},
        "measurements": {tag: value for tag, value in (state.get("measurements") or {}).items()},
        "provenance": {key: snapshot.get(key) for key in
                       ("model_fingerprint", "source_rules_fingerprint")},
    }


def snapshot_catalog(snapshots: list[dict], offset: int = 0, limit: int = 50) -> dict:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_SNAPSHOTS:
        raise ValueError("Каталог: offset ≥ 0, limit от 1 до 100, только целые числа")
    ordered = sorted(snapshots, key=lambda item: local_moment(item["at"]))
    keys = [snapshot_id(item) for item in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("Каталог содержит повторяющийся идентификатор среза")
    end = offset + limit
    return {
        "schema_version": "history.v1", "timezone": "source-local", "grid_minutes": 10,
        "items": [snapshot_item(item) for item in ordered[offset:end]], "total": len(ordered),
        "next_offset": end if end < len(ordered) else None,
        "snapshot_coverage": {"start": ordered[0]["at"], "end": ordered[-1]["at"]} if ordered else None,
        "arbitrary": {"available": False, "reason": "Полный период данных не подключён"},
        "note": "История описывает наблюдавшиеся условия, а не последствия неисполненного действия.",
    }
