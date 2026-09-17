"""Замороженные реальные срезы (C3): состояние, доверие, прогноз и измерения на момент 2026 года.

Срез делается командой `snapshot` там, где есть `task/` и `model.pkl`, и кладётся в
`artifacts/snapshots/`. Демонстрация (`serve`, `scenes`) читает срезы без исходных данных и
проходит через тот же связыватель, что и `advise`. Срез привязан к отпечатку модели: срез от
другой модели не загружается.
"""
import json
from pathlib import Path

import pandas as pd

from neftecode.application.contracts import LiveForecast, LiveSnapshot
from neftecode.application.services.trust import DataTrustAgent
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.live.advisor import (MEASURED_ORIGIN, MEASURED_TAGS, LocalForecastScenarioBinder,
                                                   forecast_at, state_at)
from neftecode.infrastructure.live.origin import validate_origin

SCHEMA_VERSION = "v1"
FOLDER = "snapshots"
SYNTHETIC_ORIGIN = "synthetic_scenario_state"


def snapshot_name(snapshot: dict) -> str:
    stamp = pd.Timestamp(snapshot["at"]).strftime("%Y%m%d-%H%M%S")
    return stamp + ("-synthetic" if snapshot.get("synthetic_edits") else "")


def build_snapshot(signals, lab, online, bundle: dict, at, label: str = "", why: str = "",
                   synthetic_missing: tuple[str, ...] = (), coverage: dict | None = None,
                   source_rules_fingerprint: str | None = None) -> dict:
    """Один момент: то, что `advise` увидел бы в этот момент, без решения."""
    when = validate_origin(at, bundle)
    state = state_at(signals, lab, online, bundle, when)
    edits = []
    for tag in synthetic_missing:
        if tag not in MEASURED_TAGS:
            raise ValueError(f"Синтетическое затирание: неизвестный тег {tag}")
        state["measurements"][tag] = None
        edits.append(f"{tag}: измерение затёрто искусственно (в данных такого момента нет)")
    if edits:
        state["synthetic_edits"] = edits
    trust = DataTrustAgent(bundle["config"]).assess(state).to_dict()
    forecast = forecast_at(signals, lab, online, bundle, when, fallback=trust.get("fallback", False))
    if coverage:
        forecast = {**forecast, **coverage}
    return {"schema_version": SCHEMA_VERSION, "at": when.isoformat(), "label": label, "why": why,
            "state": state, "trust": trust, "forecast": forecast,
            "measured": dict(state.get("measurements") or {}),
            "synthetic_edits": edits,
            "model_fingerprint": (bundle.get("manifest") or {}).get("fingerprint"),
            "source_rules_fingerprint": source_rules_fingerprint}


def write_snapshot(out: Path, snapshot: dict) -> Path:
    folder = Path(out) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snapshot_name(snapshot)}.json"
    write_json(path, snapshot)
    return path


def _validate(value, where: str, expected_fingerprint: str | None) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Срез {where}: ожидается schema_version={SCHEMA_VERSION!r}")
    for key in ("at", "state", "trust", "forecast", "measured"):
        if key not in value:
            raise ValueError(f"Срез {where}: нет поля {key}")
    if not isinstance(value["state"], dict) or value["state"].get("origin") != MEASURED_ORIGIN:
        raise ValueError(f"Срез {where}: состояние должно быть реальным ({MEASURED_ORIGIN})")
    if expected_fingerprint and value.get("model_fingerprint") != expected_fingerprint:
        raise ValueError(f"Срез {where} сделан для другой модели ({value.get('model_fingerprint')!r}); "
                         f"пересоберите срезы командой snapshot")
    return value


def load_snapshots(out: Path) -> list[dict]:
    """Все срезы из `out/snapshots/`, по времени; отпечаток сверяется с `out/manifest.json`, если он есть."""
    folder = Path(out) / FOLDER
    if not folder.is_dir():
        return []
    manifest = Path(out) / "manifest.json"
    expected = None
    if manifest.exists():
        expected = json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint")
    items = []
    for path in sorted(folder.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Срез {path} не читается: {exc}") from exc
        items.append(_validate(value, str(path), expected))
    return sorted(items, key=lambda item: item["at"])



def bind_snapshot(raw: dict, state: dict, snapshot: dict, response_model: dict | None, trust_cfg: dict):
    """Тот же связыватель, что в live: прогноз и измерения среза входят в копию сценария.

    При отказе по данным или недоступном прогнозе сценарий не связывается: решение по такому
    состоянию выносит ядро (отказ), а не подставленные числа.
    """
    trust = DataTrustAgent(trust_cfg).assess(state)
    forecast = LiveForecast.from_dict(snapshot["forecast"])
    if not trust.usable or not forecast.available:
        return parse_scenario(raw), raw
    live = LiveSnapshot(state.get("decision_time") or snapshot["at"], state, trust.to_dict(), trust_cfg=trust_cfg)
    return LocalForecastScenarioBinder(response_model).bind(raw, forecast, live)
