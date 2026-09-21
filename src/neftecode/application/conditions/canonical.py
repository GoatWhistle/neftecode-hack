from .changes import ConditionsError
from .faults import SOURCE_FAULTS

PANEL_NUMBERS = ("crude_sulfur_wt_pct", "product_sulfur_mgkg", "product_t95_c", "product_cetane_number",
                 "throughput_tph")


def defaults_for(raw: dict) -> dict:
    product = raw.get("product", {})
    return {
        "crude_sulfur_wt_pct": raw["crude"]["sulfur_wt_pct"]["value"],
        "product_sulfur_mgkg": (product.get("sulfur_mgkg") or {}).get("value"),
        "product_t95_c": (product.get("t95_c") or {}).get("value"),
        "product_cetane_number": (product.get("cetane_number") or {}).get("value"),
        "throughput_tph": raw["current_operation"]["throughput"]["value"],
        "tanks": [{"id": t["tank_id"],
                   "inventory": None if t.get("on_demand") else t["inventory"]["value"],
                   "on_demand": bool(t.get("on_demand", False)),
                   "available": t["available"]} for t in raw["tanks"]],
    }


def _number(conditions: dict, key: str):
    value = conditions.get(key)
    return None if value is None or value == "" else float(value)


def changes_from(conditions: dict, raw: dict) -> list[dict]:
    """Правки сценария по условиям панели: только поля, отличные от значений сценария.

    `conditions` — простые значения (числа и строки, None — поле не задано): разобранная query-строка
    или результат `canonical_conditions`.
    """
    defaults = defaults_for(raw)
    changes = []
    for name, change in (("crude_sulfur_wt_pct", "crude_sulfur_wt_pct"),
                          ("product_sulfur_mgkg", "product_sulfur_mgkg"),
                          ("product_t95_c", "product_t95_c"),
                          ("product_cetane_number", "product_cetane_number"),
                          ("throughput_tph", "throughput_tph")):
        value = _number(conditions, name)
        if value is None or defaults.get(name) is None:
            continue
        if abs(value - float(defaults[name])) > 1e-9:
            changes.append({"change": change, "value": value})
    tank = conditions.get("tank") or ""
    if tank:
        current = next((t for t in defaults["tanks"] if t["id"] == tank), None)
        stock = _number(conditions, "tank_inventory")
        if current and stock is not None and current["inventory"] is not None \
                and abs(stock - float(current["inventory"])) > 1e-9:
            changes.append({"change": "tank_inventory", "value": stock, "target": tank})
        raw_available = conditions.get("tank_available") or ""
        if current and raw_available in ("0", "1"):
            available = raw_available == "1"
            if available != bool(current["available"]):
                changes.append({"change": "tank_available", "value": available, "target": tank})
    return changes


def canonical_conditions(conditions: dict, raw: dict, name: str, default_snapshot: str) -> dict:
    """Полные условия расчёта: незаданные поля панели дополняются значениями сценария.

    Одинаковые условия дают одинаковый словарь — по нему кэшируется решение.
    """
    defaults = defaults_for(raw)
    fault = conditions.get("fault")
    fault = "healthy" if fault is None else fault
    if fault not in SOURCE_FAULTS:
        raise ConditionsError(f"Неизвестный отказ источника «{fault}»")
    snapshot = conditions.get("snapshot")
    out = {"scenario": name, "fault": fault, "snapshot": default_snapshot if snapshot is None else snapshot}
    for key in PANEL_NUMBERS:
        value = conditions.get(key)
        out[key] = defaults.get(key) if value is None else value
    tanks = defaults["tanks"]
    tank = conditions.get("tank") or (tanks[0]["id"] if tanks else "")
    current = next((t for t in tanks if t["id"] == tank), None)
    stock = conditions.get("tank_inventory")
    available = conditions.get("tank_available") or ""
    out["tank"] = tank
    out["tank_inventory"] = (current["inventory"] if current else None) if stock is None else stock
    out["tank_available"] = (("1" if current["available"] else "0") if current else "") \
        if available not in ("0", "1") else available
    return out
