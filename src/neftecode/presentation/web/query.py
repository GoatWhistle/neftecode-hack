from neftecode.application.conditions import PANEL_NUMBERS


class DemoServerError(ValueError):
    pass


def _first(values: dict, key: str) -> str | None:
    return (values.get(key) or [None])[0]


def _number(values: dict, key: str):
    raw = (values.get(key) or [""])[0].strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise DemoServerError(f"{key}: ожидается число, получено «{raw}»") from exc


def parse_conditions(values: dict) -> dict:
    """Разбор query-строки панели условий (`parse_qs`) в простые значения; None — поле не задано."""
    out = {key: _first(values, key) for key in ("fault", "snapshot", "tank", "at")}
    for key in (*PANEL_NUMBERS, "tank_inventory"):
        out[key] = _number(values, key)
    out["tank_available"] = _first(values, "tank_available")
    return out
