from collections.abc import Iterable
import copy
import math

TEMPERATURE = "ht_reactor_inlet_temp_c"
HYDROTREATING_CONTROLS = (TEMPERATURE, "ht_feed_flow_m3h")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _moves(plan, base_controls: dict, confirmed: Iterable, names: tuple[str, ...]) -> bool:
    for _, controls in confirmed or ():
        for name in names:
            if name in controls and abs(float(controls[name]) - float(base_controls.get(name, controls[name]))) > 1e-9:
                return True
    for step in plan.steps:
        for name in names:
            if name in step.controls and name in base_controls \
                    and abs(float(step.controls[name]) - float(base_controls[name])) > 1e-9:
                return True
    return False


def moves_temperature(plan, base_controls: dict, confirmed: Iterable = ()) -> bool:
    return _moves(plan, base_controls, confirmed, (TEMPERATURE,))


def moves_hydrotreating(plan, base_controls: dict, confirmed: Iterable = ()) -> bool:
    return _moves(plan, base_controls, confirmed, HYDROTREATING_CONTROLS)


def weak_response_factor(raw: dict) -> float | None:
    model = (((raw.get("stages") or {}).get("hydrotreating") or {}).get("model") or {})
    beta, bounds = model.get("beta_mgkg_per_c"), model.get("weak_strong")
    if model.get("provenance") != "derived" or not _finite(beta) or beta == 0:
        return None
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2 or not _finite(bounds[0]):
        return None
    factor = bounds[0] / beta
    return factor if factor > 0 else None


def weak_response_raw(raw: dict) -> dict | None:
    factor = weak_response_factor(raw)
    if factor is None:
        return None
    out = copy.deepcopy(raw)
    model = out["stages"]["hydrotreating"]["model"]
    model["conversion_per_degree"] = float(model["conversion_per_degree"]) * factor
    model["beta_mgkg_per_c"] = float(model["weak_strong"][0])
    return out
