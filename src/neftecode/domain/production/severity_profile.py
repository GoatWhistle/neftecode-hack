import math

PROFILE_VERSION = "severity-profile/1"
TERMS = ("temperature_above_reference", "throughput_above_reference")
DEFAULT_WEIGHTS = {"temperature_above_reference": 0.7, "throughput_above_reference": 0.3}
SCENARIO_PROXY = "scenario_proxy"

SCOPE = ("Это описанный индекс режима, а не возраст катализатора, не остаточный ресурс "
         "и не вероятность отказа: дат замен, наработки и разметки отказов в пакете нет.")


class SeverityProfileError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def build_profile(reference_temp_c, temp_max_c, reference_flow_m3h, flow_max_m3h, weights=None, temp_min_c=None,
                  model_region: dict | None = None, max_severity_index=None,
                  source: str = SCENARIO_PROXY, origin: str = "") -> dict | None:
    """Фиксированная опора и масштаб тяжести режима из исходных параметров сценария.

    Возвращает None, если опоры или масштабы неизвестны либо масштаб не положителен:
    индекс тогда недоступен, а не равен нулю.
    """
    if not all(_finite(v) for v in (reference_temp_c, temp_max_c, reference_flow_m3h, flow_max_m3h)):
        return None
    temp_scale = float(temp_max_c) - float(reference_temp_c)
    flow_scale = float(flow_max_m3h) - float(reference_flow_m3h)
    if temp_scale <= 0 or flow_scale <= 0:
        return None
    used = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
    unknown = set(used) - set(TERMS)
    if unknown:
        raise SeverityProfileError(
            f"policy.severity_weights: неизвестные слагаемые {', '.join(sorted(unknown))}")
    if any(not _finite(w) or w < 0 for w in used.values()):
        raise SeverityProfileError("policy.severity_weights: веса должны быть конечными и неотрицательными")
    profile = {
        "version": PROFILE_VERSION,
        "source": source,
        "origin": origin or ("Исходные сценарные опорная точка и верхняя граница гидроочистки, заданные "
                             "до привязки измерений; не меняются вместе с текущим режимом."),
        "reference_temp_c": float(reference_temp_c), "temp_scale_c": temp_scale,
        "reference_flow_m3h": float(reference_flow_m3h), "flow_scale_m3h": flow_scale,
        "weights": used,
        "scope": SCOPE,
        "applicability": ("Сценарный прокси тяжести: сравнимы только значения с одной версией "
                          "и одними опорами профиля."),
    }
    if model_region:
        profile["model_region"] = model_region
    profile["scenario_limits"] = {"temp_max_c": float(temp_max_c),
                                  "temp_range_c": ([float(temp_min_c), float(temp_max_c)]
                                                   if _finite(temp_min_c) else None),
                                  "max_severity_index": (float(max_severity_index)
                                                         if _finite(max_severity_index) else None)}
    return profile


def profile_id(profile: dict) -> str:
    weights = profile.get("weights") or {}
    weight_text = "/".join(f"{float(weights.get(name, 0.0)):g}" for name in TERMS)
    return (f"{profile['version']}:{profile['source']}:T{profile['reference_temp_c']:g}/"
            f"{profile['temp_scale_c']:g}:F{profile['reference_flow_m3h']:g}/{profile['flow_scale_m3h']:g}"
            f":W{weight_text}")


def _limits(profile: dict, temp: float, index: float) -> list[dict]:
    limits = [{"kind": "passport", "label": "Паспортный предел оборудования", "known": False,
               "note": "Не задан: запас до паспортного предела не оценивается."}]
    region = profile.get("model_region") or {}
    t6 = region.get("t6_range_c")
    if isinstance(t6, (list, tuple)) and len(t6) == 2 and all(_finite(v) for v in t6):
        limits.append({"kind": "model_region", "label": "Историческая область модели отклика (T6)",
                       "known": True, "unit": "°C", "bounds": [float(t6[0]), float(t6[1])],
                       "headroom": float(t6[1]) - temp,
                       "note": "Граница применимости модели, не предел безопасной работы оборудования."})
    else:
        limits.append({"kind": "model_region", "label": "Историческая область модели отклика (T6)",
                       "known": False, "note": "Область не задана: запас не оценивается."})
    scenario = profile.get("scenario_limits") or {}
    temp_max = scenario.get("temp_max_c")
    max_index = scenario.get("max_severity_index")
    known = _finite(temp_max) or _finite(max_index)
    entry = {"kind": "scenario", "label": "Сценарный предел", "known": known,
             "note": "Задан сценарием, не заводом."}
    if _finite(temp_max):
        entry.update({"unit": "°C", "bound": float(temp_max), "headroom": float(temp_max) - temp})
    if _finite(max_index):
        entry.update({"max_severity_index": float(max_index), "index_headroom": float(max_index) - index})
    limits.append(entry)
    return limits


def evaluate(profile: dict | None, temp, flow, reason_missing: str) -> dict:
    if profile is None:
        return {"available": False, "index": None, "reason": reason_missing}
    if not _finite(temp) or not _finite(flow):
        return {"available": False, "index": None, "profile_version": profile["version"],
                "reason": "Уставки гидроочистки неизвестны: тяжесть режима не считается"}
    raw = {"temperature_above_reference": max(0.0, temp - profile["reference_temp_c"]),
           "throughput_above_reference": max(0.0, flow - profile["reference_flow_m3h"])}
    scale = {"temperature_above_reference": profile["temp_scale_c"],
             "throughput_above_reference": profile["flow_scale_m3h"]}
    units = {"temperature_above_reference": "°C", "throughput_above_reference": "м3/ч"}
    terms = {name: raw[name] / scale[name] for name in TERMS}
    weights = profile["weights"]
    components = [{"term": name, "excess": raw[name], "unit": units[name], "scale": scale[name],
                   "value": terms[name], "weight": weights.get(name, 0.0),
                   "contribution": weights.get(name, 0.0) * terms[name]} for name in TERMS]
    index = sum(c["contribution"] for c in components)
    return {
        "available": True, "index": float(index), "terms": terms, "weights": dict(weights),
        "components": components, "profile_version": profile["version"], "profile_id": profile_id(profile),
        "profile": {k: profile[k] for k in ("version", "source", "origin", "reference_temp_c", "temp_scale_c",
                                            "reference_flow_m3h", "flow_scale_m3h", "applicability")},
        "reference_temp_c": profile["reference_temp_c"], "reference_flow_m3h": profile["reference_flow_m3h"],
        "control_range_c": (profile.get("scenario_limits") or {}).get("temp_range_c"),
        "temp_c": float(temp), "flow_m3h": float(flow),
        "limits": _limits(profile, float(temp), float(index)),
        "reason": "Показатель тяжести режима собран из наблюдаемых слагаемых с явными весами.",
        "basis": "Слагаемые считаются относительно фиксированной опоры профиля, а не текущего режима.",
        "scope": profile["scope"],
    }


def comparable(a: dict | None, b: dict | None) -> bool:
    return (isinstance(a, dict) and isinstance(b, dict) and a.get("available") and b.get("available")
            and a.get("profile_id") is not None and a.get("profile_id") == b.get("profile_id"))


def delta(a: dict | None, b: dict | None) -> float | None:
    return float(b["index"]) - float(a["index"]) if comparable(a, b) else None
