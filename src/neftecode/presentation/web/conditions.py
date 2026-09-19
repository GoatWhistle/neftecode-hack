import threading
from typing import Callable

from neftecode.presentation.demo import SOURCE_FAULTS

class DemoServerError(ValueError):
    pass


def _number(values: dict, key: str):
    raw = (values.get(key) or [""])[0].strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise DemoServerError(f"{key}: ожидается число, получено «{raw}»") from exc


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


def changes_from(values: dict, raw: dict) -> list[dict]:
    defaults = defaults_for(raw)
    changes = []
    for name, change in (("crude_sulfur_wt_pct", "crude_sulfur_wt_pct"),
                          ("product_sulfur_mgkg", "product_sulfur_mgkg"),
                          ("product_t95_c", "product_t95_c"),
                          ("product_cetane_number", "product_cetane_number"),
                          ("throughput_tph", "throughput_tph")):
        value = _number(values, name)
        if value is None or defaults.get(name) is None:
            continue
        if abs(value - float(defaults[name])) > 1e-9:
            changes.append({"change": change, "value": value})
    tank = (values.get("tank") or [""])[0]
    if tank:
        current = next((t for t in defaults["tanks"] if t["id"] == tank), None)
        stock = _number(values, "tank_inventory")
        if current and stock is not None and current["inventory"] is not None \
                and abs(stock - float(current["inventory"])) > 1e-9:
            changes.append({"change": "tank_inventory", "value": stock, "target": tank})
        raw_available = (values.get("tank_available") or [""])[0]
        if current and raw_available in ("0", "1"):
            available = raw_available == "1"
            if available != bool(current["available"]):
                changes.append({"change": "tank_available", "value": available, "target": tank})
    return changes


class DecisionCache:

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict = {}

    def get(self, key, compute: Callable[[], dict]) -> dict:
        with self._lock:
            entry = self._entries.get(key)
            owner = entry is None
            if owner:
                entry = self._entries[key] = {"done": threading.Event(), "payload": None, "error": None}
        if owner:
            try:
                entry["payload"] = compute()
            except BaseException as exc:
                entry["error"] = exc
                with self._lock:
                    self._entries.pop(key, None)
            finally:
                entry["done"].set()
        else:
            entry["done"].wait()
        if entry["error"] is not None:
            raise entry["error"]
        return entry["payload"]

    def put(self, key, payload: dict) -> None:
        entry = {"done": threading.Event(), "payload": payload, "error": None}
        entry["done"].set()
        with self._lock:
            self._entries[key] = entry

    def __len__(self) -> int:
        return len(self._entries)


PANEL_NUMBERS = ("crude_sulfur_wt_pct", "product_sulfur_mgkg", "product_t95_c", "product_cetane_number",
                 "throughput_tph")


def canonical_conditions(values: dict, raw: dict, name: str, default_snapshot: str) -> dict:
    defaults = defaults_for(raw)
    fault = (values.get("fault") or ["healthy"])[0]
    if fault not in SOURCE_FAULTS:
        raise DemoServerError(f"Неизвестный отказ источника «{fault}»")
    out = {"scenario": name, "fault": fault, "snapshot": (values.get("snapshot") or [default_snapshot])[0]}
    for key in PANEL_NUMBERS:
        value = _number(values, key)
        out[key] = defaults.get(key) if value is None else value
    tanks = defaults["tanks"]
    tank = (values.get("tank") or [""])[0] or (tanks[0]["id"] if tanks else "")
    current = next((t for t in tanks if t["id"] == tank), None)
    stock = _number(values, "tank_inventory")
    available = (values.get("tank_available") or [""])[0]
    out["tank"] = tank
    out["tank_inventory"] = (current["inventory"] if current else None) if stock is None else stock
    out["tank_available"] = (("1" if current["available"] else "0") if current else "") \
        if available not in ("0", "1") else available
    return out


def cache_key(canonical: dict) -> tuple:
    return tuple(sorted(canonical.items()))


def as_query(canonical: dict) -> dict:
    return {k: [str(v)] for k, v in canonical.items() if v is not None and v != ""}


