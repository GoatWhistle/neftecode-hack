"""Data process: scenarios and point-in-time feature snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd

from neftecode.infrastructure.data.data import build_features, load_sources
from neftecode.application.services.trust import DataTrustAgent
from .common import Request, ServiceError, ServiceSettings, serve, clean, content_hash


class DataService:
    def __init__(self, root: str | Path = ".", artifacts: str | Path = "artifacts"):
        self.root = Path(root).resolve()
        self.artifacts = Path(artifacts).resolve()
        self._sources_cache = None
        self._config_cache = None
        self._lock = Lock()

    @property
    def scenario_dir(self) -> Path:
        return self.root / "config" / "scenarios"

    def scenarios(self) -> list[str]:
        return sorted(path.stem for path in self.scenario_dir.glob("*.json"))

    def scenario(self, scenario_id: str) -> dict[str, Any]:
        if not isinstance(scenario_id, str) or not scenario_id or "/" in scenario_id or "\\" in scenario_id:
            raise ServiceError("scenario_id должен быть именем сценария", 400, "invalid_scenario_id")
        if scenario_id not in self.scenarios():
            raise ServiceError(f"Сценарий «{scenario_id}» не найден", 404, "scenario_not_found")
        try:
            value = json.loads((self.scenario_dir / f"{scenario_id}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ServiceError("Сценарий недоступен", 503, "scenario_unavailable", retryable=True) from exc
        if not isinstance(value, dict):
            raise ServiceError("Сценарий должен быть JSON-объектом", 503, "invalid_scenario")
        return clean(value)

    def _config(self) -> dict:
        if self._config_cache is None:
            path = self.root / "config" / "experiment.json"
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ServiceError("Конфигурация эксперимента недоступна", 503, "config_unavailable", retryable=True) from exc
            if not isinstance(value, dict):
                raise ServiceError("Конфигурация эксперимента некорректна", 503, "invalid_config")
            self._config_cache = value
        return self._config_cache

    def _sources(self):
        if self._sources_cache is None:
            with self._lock:
                if self._sources_cache is None:
                    task = self.root / "task"
                    try:
                        self._sources_cache = load_sources(task)
                    except (OSError, StopIteration, ValueError) as exc:
                        raise ServiceError("Измерения task недоступны", 503, "measurements_unavailable",
                                           retryable=True) from exc
        return self._sources_cache

    def measurements_available(self) -> bool:
        task = self.root / "task"
        required = [task / "data" / "avt_tags.csv", task / "data" / "242000_tags.csv"]
        return all(path.is_file() for path in required) and any(task.glob("ЛИМС*.xlsx")) and any(task.glob("Выгрузка*.xlsx"))

    def capabilities(self) -> dict[str, Any]:
        return {"scenarios": bool(self.scenarios()), "measurements": self.measurements_available(),
                "snapshots": self.measurements_available()}

    @staticmethod
    def _state(meta: pd.DataFrame) -> dict[str, Any]:
        row = meta.iloc[0]
        result = {}
        for key, value in row.items():
            if pd.isna(value):
                result[key] = None
            elif isinstance(value, pd.Timestamp):
                result[key] = value.isoformat()
            elif hasattr(value, "item"):
                result[key] = value.item()
            else:
                result[key] = value
        return clean(result)

    def snapshot(self, at: str) -> dict[str, Any]:
        if not isinstance(at, str) or not at.strip():
            raise ServiceError("Нужно указать at", 400, "invalid_at")
        signals, lab, online = self._sources()
        cfg = self._config()
        try:
            when = pd.Timestamp(at)
        except (TypeError, ValueError) as exc:
            raise ServiceError("Некорректное время at", 422, "invalid_at") from exc
        if pd.isna(when) or when.tzinfo is not None:
            raise ServiceError("at должен быть местным временем без часового пояса", 422, "invalid_at")
        if when < signals.index.min() or when > signals.index.max():
            raise ServiceError("at вне диапазона телеметрии", 422, "snapshot_out_of_range")
        try:
            features, meta = build_features(signals, lab, online, [when], cfg)
        except (ValueError, TypeError, KeyError) as exc:
            raise ServiceError(str(exc), 422, "snapshot_rejected") from exc
        state = self._state(meta)
        state["origin"] = "real_measurements_at_decision_time"
        trust = DataTrustAgent(cfg).assess(state).to_dict()
        feature_map = clean(features.iloc[0].to_dict())
        source_period = {"min": signals.index.min().isoformat(), "max": signals.index.max().isoformat()}
        schema = [{"name": str(name), "type": str(features[name].dtype)} for name in features.columns]
        result = {"schema_version": "v1", "at": when.isoformat(), "state": state,
                  "trust": clean(trust), "features": feature_map,
                  "source_period": source_period, "feature_schema": schema,
                  "feature_schema_hash": content_hash(schema)}
        result["snapshot_id"] = content_hash(result)
        return result

    def routes(self):
        return {"/v1/scenarios": lambda request: {"scenarios": self.scenarios()},
                "/v1/scenarios/get": self._get_scenario,
                "/v1/capabilities": lambda request: self.capabilities(),
                "/v1/snapshots": self._snapshot}

    def _get_scenario(self, request: Request):
        body = request.body
        if not isinstance(body, dict):
            raise ServiceError("Тело запроса должно быть JSON-объектом", 400, "invalid_body")
        return self.scenario(body.get("scenario_id"))

    def _snapshot(self, request: Request):
        body = request.body
        if not isinstance(body, dict):
            raise ServiceError("Тело запроса должно быть JSON-объектом", 400, "invalid_body")
        return self.snapshot(body.get("at"))

    def ready(self) -> bool:
        names = self.scenarios()
        if not names:
            return False
        try:
            for name in names:
                self.scenario(name)
        except ServiceError:
            return False
        return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Нефтекод data service")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    env = ServiceSettings.from_env("NEFTECODE_DATA_")
    settings = ServiceSettings(host=args.host or env.host, port=args.port or 8766,
                                request_timeout_s=env.request_timeout_s, shutdown_timeout_s=env.shutdown_timeout_s,
                                max_workers=env.max_workers, max_body_bytes=env.max_body_bytes,
                                max_response_bytes=env.max_response_bytes)
    service = DataService(args.root, args.artifacts)
    return serve(service.routes(), settings, service.ready, "data-service")


if __name__ == "__main__":
    main()
