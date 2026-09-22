import json
from pathlib import Path

import pandas as pd

from neftecode.application.contracts import LiveForecast, LiveSnapshot
from neftecode.application.ports.live import ForecastBindingError
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


def _with_coverage(forecast: dict, coverage: dict | None) -> dict:
    if not coverage:
        return forecast
    applied = coverage
    if "coverage_target" not in coverage:
        applied = coverage.get(forecast.get("model"), {})
    return {**forecast, **applied}


def build_snapshot(signals, lab, online, bundle: dict, at, label: str = "", why: str = "",
                   synthetic_missing: tuple[str, ...] = (), coverage: dict | None = None,
                   source_rules_fingerprint: str | None = None) -> dict:
    """Собирает срез момента `at`.

    Дефект #1 (task-pool.md, I1): срез хранит ОБА прогноза, посчитанных на момент сборки —
    основной (`forecast`, источники доверены, fallback=False) и резервный no-PAK
    (`forecast_no_pak`, fallback=True), — а не только тот, что соответствовал доверию source'ов
    в момент сборки. Это позволяет `bind_snapshot` выбирать прогноз ПОСЛЕ инъекции отказа
    источника (например, `frozen_pak`) по пересчитанному на актуальном состоянии
    `trust.fallback_mode`, а не эхом того, что было доверено при сборке среза.
    """
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
    forecast = _with_coverage(forecast_at(signals, lab, online, bundle, when, fallback=False), coverage)
    forecast_no_pak = _with_coverage(forecast_at(signals, lab, online, bundle, when, fallback=True), coverage)
    return {"schema_version": SCHEMA_VERSION, "at": when.isoformat(), "label": label, "why": why,
            "state": state, "trust": trust, "forecast": forecast, "forecast_no_pak": forecast_no_pak,
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
        except (OSError, ValueError) as exc:
            raise ValueError(f"Срез {path} не читается ({type(exc).__name__}: {exc}): удалите файл или "
                             f"пересоберите срезы командой `uv run neftecode snapshot --all`") from exc
        items.append((path, _validate(value, str(path), expected)))
    # Идентификатор среза (время + признак synthetic) — ключ во всех путях: каталог, выбор
    # в UI, serve и gateway. Два среза с одним ключом неразличимы, поэтому поставка с дублем
    # отклоняется целиком с именами файлов, а не решается молчаливым выбором одного из них.
    seen: dict[str, Path] = {}
    for path, value in items:
        key = snapshot_name(value)
        if key in seen:
            raise ValueError(f"Срезы {seen[key].name} и {path.name} имеют один идентификатор {key}: "
                             f"поставка с неразличимыми срезами не поддерживается")
        seen[key] = path
    return sorted((value for _, value in items), key=lambda item: item["at"])



def select_forecast_dict(snapshot: dict, trust) -> dict:
    """Выбирает, какой из двух прогнозов, сохранённых в срезе, использовать — ПО
    ПЕРЕСЧИТАННОМУ доверию (`trust`, обычно `DataTrustAgent(...).assess(state)` на актуальном
    состоянии), а не по доверию, зафиксированному в срезе на момент его сборки.

    Дефект #1: если после сборки среза источник отказал (например, инъекция `frozen_pak`),
    пересчитанный `trust.fallback_mode` становится `True`, и в этом случае нужно взять
    резервный `snapshot["forecast_no_pak"]`, а не основной `snapshot["forecast"]`. Общая
    функция для `bind_snapshot` и для отображения прогноза (demo/gateway/decision-service),
    чтобы решение и показанный прогноз никогда не расходились.

    Старый срез без `forecast_no_pak` нельзя безопасно использовать в fallback-режиме:
    основной прогноз может зависеть от потерявшего доверие ПАК. Такой срез нужно пересобрать.
    """
    fallback_mode = getattr(trust, "fallback_mode", None)
    if fallback_mode is None:
        fallback_mode = trust.get("fallback", False) if isinstance(trust, dict) else False
    usable = getattr(trust, "usable", None)
    if usable is None:
        usable = trust.get("usable") if isinstance(trust, dict) else None
    if usable is False:
        return snapshot.get("forecast_no_pak", snapshot["forecast"])
    if fallback_mode and "forecast_no_pak" not in snapshot:
        raise ForecastBindingError(
            "В срезе нет независимого прогноза без ПАК; пересоберите срезы командой "
            "`uv run neftecode snapshot --all`"
        )
    key = "forecast_no_pak" if fallback_mode else "forecast"
    forecast = snapshot[key]
    if forecast.get("available") is not True:
        raise ForecastBindingError(
            forecast.get("reason") or "Обязательный прогноз недоступен; решение не выдаётся"
        )
    return forecast


def bind_snapshot(raw: dict, state: dict, snapshot: dict, response_model: dict | None, trust_cfg: dict):
    """Связывает срез со сценарием, выбирая прогноз по пересчитанному доверию к текущему
    состоянию (`state`) через `select_forecast_dict` (см. её докстринг про дефект #1)."""
    trust = DataTrustAgent(trust_cfg).assess(state)
    if not trust.usable:
        return parse_scenario(raw), raw
    forecast = LiveForecast.from_dict(select_forecast_dict(snapshot, trust))
    live = LiveSnapshot(state.get("decision_time") or snapshot["at"], state, trust.to_dict(), trust_cfg=trust_cfg)
    return LocalForecastScenarioBinder(response_model).bind(raw, forecast, live)
