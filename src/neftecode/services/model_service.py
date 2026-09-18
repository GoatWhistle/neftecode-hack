"""Model process: guarded loading and point forecasts over JSON feature maps."""
from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd

from neftecode.infrastructure.ml.forecast import interval, predict_candidate
from neftecode.infrastructure.live.advisor import interval_coverage
from neftecode.infrastructure.live.origin import validate_origin
from .common import ServiceError, ServiceSettings, serve, content_hash


class ModelService:
    def __init__(self, root: str | Path = ".", artifacts: str | Path = "artifacts"):
        self.root = Path(root).resolve(); self.artifacts = Path(artifacts).resolve()
        self._bundle = None; self._lock = Lock()

    @property
    def model_path(self) -> Path:
        return self.artifacts / "model.pkl"

    def _load(self) -> dict:
        if self._bundle is None:
            with self._lock:
                if self._bundle is None:
                    if not self.model_path.is_file():
                        raise ServiceError("Артефакт модели отсутствует", 503, "model_unavailable", retryable=True)
                    try:
                        with self.model_path.open("rb") as stream:
                            bundle = pickle.load(stream)
                    except (OSError, EOFError, pickle.PickleError, AttributeError, ImportError, ValueError) as exc:
                        raise ServiceError("Артефакт модели недоступен", 503, "model_unavailable", retryable=True) from exc
                    required = ("config", "models", "columns", "selected", "fallback", "radii", "manifest")
                    if (not isinstance(bundle, dict) or any(key not in bundle for key in required)
                            or not isinstance(bundle.get("models"), dict)
                            or not isinstance(bundle.get("columns"), dict)
                            or not isinstance(bundle.get("radii"), dict)
                            or not isinstance(bundle.get("manifest"), dict)):
                        raise ServiceError("Артефакт модели некорректен", 503, "invalid_model")
                    try:
                        manifest = json.loads((self.artifacts / "manifest.json").read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        raise ServiceError("Манифест модели отсутствует", 503, "model_unavailable", retryable=True) from exc
                    if not isinstance(manifest, dict) or manifest.get("fingerprint") != bundle["manifest"].get("fingerprint"):
                        raise ServiceError("Манифест модели не соответствует bundle", 503, "model_manifest_mismatch")
                    self._bundle = bundle
        return self._bundle

    def ready(self) -> bool:
        try:
            self._load()
        except ServiceError:
            return False
        return True

    def models(self):
        bundle = self._load()
        available = bundle.get("candidates") or [*bundle["models"], "last_lab", "last_pak"]
        return {"models": sorted(set(str(name) for name in available)),
                "selected": bundle.get("selected"), "fallback": bundle.get("fallback")}

    def forecast(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ServiceError("Тело запроса должно быть JSON-объектом", 400, "invalid_body")
        snapshot = body.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ServiceError("Нужно передать полный snapshot", 400, "invalid_snapshot")
        bundle = self._load()
        self._validate_snapshot(snapshot, bundle)
        at, features = snapshot["at"], snapshot["features"]
        try:
            when = validate_origin(at, bundle)
        except (ValueError, TypeError) as exc:
            raise ServiceError(str(exc), 422, "forecast_rejected") from exc
        fallback = bool(body.get("fallback", False))
        name = bundle.get("fallback") if fallback else bundle.get("selected")
        if not isinstance(name, str) or (name not in ("last_lab", "last_pak", "last_pak_bc")
                                         and name not in bundle["models"]):
            raise ServiceError("Выбранная модель отсутствует", 503, "model_unavailable", retryable=True)
        columns = (["lab.target" if "lab.target" in features else "lab.sulfur"]
                   if name == "last_lab" else ["pak.sulfur"] if name == "last_pak"
                   else ["pak.sulfur", "pak.lab_bias20"] if name == "last_pak_bc"
                   else bundle.get("columns", {}).get(name))
        if not isinstance(columns, (list, tuple)) or name not in bundle.get("radii", {}):
            raise ServiceError("У модели отсутствует список признаков", 503, "invalid_model")
        try:
            frame = pd.DataFrame([{column: features.get(column) for column in columns}], columns=columns)
            value = float(predict_candidate(bundle, name, frame)[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError("Признаки не подходят модели", 422, "invalid_features") from exc
        if not math.isfinite(value):
            return {"at": when.isoformat(), "model": name, "value": None, "lower": None, "upper": None,
                    "available": False, "reason": "Выбранный прогноз недоступен на этот момент"}
        low, high = interval(value, bundle["radii"][name])
        reason = "Прогноз лабораторной серы после гидроочистки на горизонт эксперимента"
        if name == "last_pak_bc":
            reason += "; ПАК скорректирован причинной медианой 20 последних доступных пар ЛИМС−ПАК"
        return {"at": when.isoformat(), "model": name, "value": value, "lower": float(low), "upper": float(high),
                **interval_coverage(self.artifacts, bundle, name),
                "available": True, "reason": reason}

    @staticmethod
    def _validate_snapshot(snapshot: dict, bundle: dict):
        required = ("schema_version", "snapshot_id", "at", "state", "trust", "features",
                    "source_period", "feature_schema", "feature_schema_hash")
        if any(key not in snapshot for key in required) or snapshot.get("schema_version") != "v1":
            raise ServiceError("Snapshot имеет неполную структуру", 422, "invalid_snapshot")
        if not isinstance(snapshot["features"], dict) or not isinstance(snapshot["state"], dict):
            raise ServiceError("Snapshot содержит некорректные state/features", 422, "invalid_snapshot")
        if not isinstance(snapshot["trust"], dict) or snapshot["trust"].get("usable") is not True:
            raise ServiceError("Источники snapshot не пригодны для прогноза", 422, "snapshot_not_usable")
        schema = snapshot["feature_schema"]
        if not isinstance(schema, list) or content_hash(schema) != snapshot["feature_schema_hash"]:
            raise ServiceError("Подменённая схема признаков snapshot", 422, "snapshot_hash_mismatch")
        original = dict(snapshot); original.pop("snapshot_id", None)
        if content_hash(original) != snapshot["snapshot_id"]:
            raise ServiceError("Подменённый snapshot_id", 422, "snapshot_hash_mismatch")
        at = snapshot["at"]
        if snapshot["state"].get("decision_time") != at:
            raise ServiceError("at не совпадает с state.decision_time", 422, "snapshot_mismatch")
        period = snapshot["source_period"]
        if not isinstance(period, dict) or not isinstance(period.get("min"), str) or not isinstance(period.get("max"), str):
            raise ServiceError("Некорректный source_period", 422, "invalid_snapshot")
        try:
            when, lower, upper = pd.Timestamp(at), pd.Timestamp(period["min"]), pd.Timestamp(period["max"])
        except (TypeError, ValueError) as exc:
            raise ServiceError("Некорректное время snapshot", 422, "invalid_snapshot") from exc
        if pd.isna(when) or pd.isna(lower) or pd.isna(upper) or when.tzinfo is not None or not lower <= when <= upper:
            raise ServiceError("at вне source_period", 422, "snapshot_out_of_range")
        names = (bundle.get("selected"), bundle.get("fallback"))
        needed = set()
        for name in names:
            direct = {
                "last_lab": ("lab.sulfur",),
                "last_pak": ("pak.sulfur",),
                "last_pak_bc": ("pak.sulfur", "pak.lab_bias20"),
            }
            columns = direct.get(name, bundle.get("columns", {}).get(name, ()))
            needed.update(columns if isinstance(columns, (list, tuple)) else ())
        if not needed.issubset(snapshot["features"]):
            raise ServiceError("В snapshot отсутствуют признаки модели", 422, "invalid_features")

    def routes(self):
        return {"/v1/models": lambda request: self.models(), "/v1/forecast": lambda request: self.forecast(request.body)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Нефтекод model service")
    parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    env = ServiceSettings.from_env("NEFTECODE_MODEL_", ServiceSettings(port=8767))
    settings = ServiceSettings(host=args.host or env.host, port=args.port or env.port,
                                request_timeout_s=env.request_timeout_s, shutdown_timeout_s=env.shutdown_timeout_s,
                                max_workers=env.max_workers, max_body_bytes=env.max_body_bytes,
                                max_response_bytes=env.max_response_bytes)
    service = ModelService(args.root, args.artifacts)
    return serve(service.routes(), settings, service.ready, "model-service")


if __name__ == "__main__":
    main()
