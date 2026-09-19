from pathlib import Path
import json

from .constants import (CASE_MAX_LAG_HOURS, DEFAULT_HORIZON_SHARE, DEFAULT_ONSET_HOURS, RESPONSE_FILE,
                        RESPONSE_SCHEMA_VERSION, _finite_number, _pair)


def load_response_model(root: Path, out: Path | None = None) -> dict | None:
    path = (Path(out) if out is not None else Path(root) / "artifacts") / "response_model.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Модель отклика {path} не читается: {exc}") from exc
    return validate_response_model(value, str(path))


def validate_response_model(value, where: str = RESPONSE_FILE) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        raise ValueError(f"Модель отклика {where}: ожидается schema_version={RESPONSE_SCHEMA_VERSION!r}")
    if value.get("tag") != "ht.T6":
        raise ValueError(f"Модель отклика {where}: ожидается tag ht.T6, получено {value.get('tag')!r}")
    beta = value.get("beta_mgkg_per_c")
    if not _finite_number(beta) or beta >= 0:
        raise ValueError(f"Модель отклика {where}: beta_mgkg_per_c должна быть отрицательным числом")
    if not _pair(value.get("ci")) or not value["ci"][0] <= beta <= value["ci"][1]:
        raise ValueError(f"Модель отклика {where}: ci должен быть парой чисел, накрывающей beta")
    envelope = value.get("envelope_dt_c")
    if not _finite_number(envelope) or envelope <= 0:
        raise ValueError(f"Модель отклика {where}: envelope_dt_c должен быть положительным числом")
    for key in ("t6_range_c", "f9_range_tph", "weak_strong"):
        if key in value and value[key] is not None and not _pair(value[key]):
            raise ValueError(f"Модель отклика {where}: {key} должен быть парой чисел")
    estimates = value.get("estimates")
    if estimates is not None:
        if not isinstance(estimates, list) or not estimates:
            raise ValueError(f"Модель отклика {where}: estimates должен быть непустым списком оценок по τ")
        for estimate in estimates:
            if not isinstance(estimate, dict) or not isinstance(estimate.get("tau"), str) \
                    or not _finite_number(estimate.get("beta_mgkg_per_c")):
                raise ValueError(f"Модель отклика {where}: каждая оценка должна нести tau и beta_mgkg_per_c")
    flow_beta = value.get("flow_beta")
    if flow_beta is not None and not _finite_number(flow_beta):
        raise ValueError(f"Модель отклика {where}: flow_beta должен быть числом или null")
    onset = value.get("response_onset_hours", DEFAULT_ONSET_HOURS)
    if not _finite_number(onset) or not 0 <= onset <= CASE_MAX_LAG_HOURS:
        raise ValueError(f"Модель отклика {where}: response_onset_hours должен лежать в [0, {CASE_MAX_LAG_HOURS:g}] ч")
    share = value.get("horizon_response_share", DEFAULT_HORIZON_SHARE)
    if not _finite_number(share) or not 0 < share <= 1:
        raise ValueError(f"Модель отклика {where}: horizon_response_share должна лежать в (0, 1]")
    plateau = value.get("observed_plateau_window_hours")
    if plateau is not None and (not _pair(plateau) or plateau[0] < onset or plateau[0] > plateau[1]):
        raise ValueError(f"Модель отклика {where}: observed_plateau_window_hours должен быть парой "
                         "неубывающих часов после начала отклика")
    return value


def response_lag(response: dict) -> tuple[float, float]:
    return (float(response.get("response_onset_hours", DEFAULT_ONSET_HOURS)),
            float(response.get("horizon_response_share", DEFAULT_HORIZON_SHARE)))


def linearize_response(model: dict, s0: float, basis: str) -> None:
    beta, envelope = float(model["beta_mgkg_per_c"]), float(model["envelope_dt_c"])
    model["conversion_per_degree"] = -beta / s0
    model["linearization_sulfur_mgkg"] = s0
    model["note"] = (f"Отклик по данным ({model.get('response_source')}, τ={model.get('response_tau')}, "
                     f"{model.get('response_rows')} строк): β = {beta:g} мг/кг на °C, ДИ {model.get('beta_ci')}. "
                     f"k = −β/S₀ при S₀ = {s0:.3f} мг/кг ({basis}; к ней план применяет отклик): "
                     f"линеаризация exp(−kΔT) ≈ 1 + βΔT/S₀ при |ΔT| ≤ {envelope:g} °C. "
                     f"Опорные точки — измерения T6 и F9 на момент решения.")


def interval_coverage(out: Path, bundle: dict, model: str | None = None) -> dict:
    result = {}
    target = (bundle.get("config") or {}).get("interval_coverage")
    if _finite_number(target):
        result["coverage_target"] = float(target)
    path = Path(out) / "metrics.json"
    if path.exists():
        metrics = json.loads(path.read_text(encoding="utf-8"))
        name = model or bundle.get("selected")
        test = ((metrics.get("models") or {}).get(name) or {}).get("test") or {}
        if _finite_number(test.get("interval_coverage")):
            result["coverage_test"] = float(test["interval_coverage"])
    return result
