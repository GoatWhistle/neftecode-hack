import hashlib
import pickle
from pathlib import Path

from neftecode.infrastructure.data.alignment import check_time_assumptions, validate_forecast_selection


def history_bundle(root: Path, raw: bytes) -> tuple[dict, list[dict]]:
    bundle = pickle.loads(raw)
    if not isinstance(bundle, dict) or "config" not in bundle:
        raise ValueError("Артефакт модели не содержит config")
    migrations = []
    selection = bundle["config"].get("forecast_selection") or {}
    old, new = "context/forecast-research/rolling-f4.json", "research/forecast/rolling-f4.json"
    if selection.get("evidence") == old:
        actual_hash = hashlib.sha256((root / new).read_bytes()).hexdigest()
        if actual_hash != selection.get("evidence_sha256"):
            raise ValueError("Перенесённое доказательство прогноза не совпадает с хешем модели")
        selection["evidence"] = new
        migrations.append({"field": "config.forecast_selection.evidence", "from": old, "to": new,
                           "verified_sha256": actual_hash})
    validate_forecast_selection(bundle["config"])
    check_time_assumptions(bundle["config"])
    return bundle, migrations
