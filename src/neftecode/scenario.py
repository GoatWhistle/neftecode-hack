"""Executable chain scenario: what is measured, what is assumed and what stays unknown.

Every physical number carries a unit and a provenance, so a scenario constant can never be
read back as if it were a plant measurement. Loading validates structure, units and ranges;
a missing optional quality is preserved as unknown instead of silently becoming a pass.
"""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path

SCHEMA = "neftecode.scenario.v1"

#: Provenance of a scenario number. See config/parameters.json for the same vocabulary.
SOURCES = ("given", "derived", "scenario", "open")

#: Units accepted for each named quantity. A scenario declaring another unit is rejected
#: rather than converted by guesswork.
UNITS = {
    "sulfur_mgkg": "мг/кг",
    "t95_c": "°C",
    "cetane_number": "ед.",
    "density_kgm3": "кг/м3",
    "mass_t": "т",
    "flow_tph": "т/ч",
    "temperature_c": "°C",
    "pressure_mpa": "МПа",
    "volume_flow_m3h": "м3/ч",
    "sulfur_wt_pct": "% масс.",
    "fraction": "доля",
    "cost_per_t": "усл.ед./т",
    "hours": "ч",
}

#: Quality properties a blended product is judged on. Expert message 517 requires all three.
QUALITIES = ("sulfur_mgkg", "t95_c", "cetane_number")

#: Which way a limit constrains the property.
QUALITY_DIRECTION = {"sulfur_mgkg": "max", "t95_c": "max", "cetane_number": "min"}


class ScenarioError(ValueError):
    """Raised with a message naming the field, so a broken scenario is fixable without reading code."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Quantity:
    """A number that always remembers its unit and where it came from."""

    value: float
    unit: str
    source: str
    note: str | None = None

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "source": self.source, "note": self.note}

    @property
    def measured(self) -> bool:
        """True only for values traceable to the issued data, never for our own assumptions."""
        return self.source in ("given", "derived")


def quantity(raw, kind: str, where: str, *, allow_negative: bool = False) -> Quantity:
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where}: ожидается объект со значением, единицей и источником, получено {type(raw).__name__}")
    missing = [k for k in ("value", "unit", "source") if k not in raw]
    if missing:
        raise ScenarioError(f"{where}: не заданы обязательные поля {', '.join(missing)}")
    value = raw["value"]
    if not _finite(value):
        raise ScenarioError(f"{where}: значение должно быть конечным числом, получено {value!r}")
    if value < 0 and not allow_negative:
        raise ScenarioError(f"{where}: отрицательное значение {value} недопустимо для этой величины")
    expected = UNITS.get(kind)
    if expected is None:
        raise ScenarioError(f"{where}: неизвестный вид величины {kind}")
    if raw["unit"] != expected:
        raise ScenarioError(f"{where}: единица «{raw['unit']}» не совпадает с ожидаемой «{expected}»; "
                            f"пересчёт по догадке запрещён")
    if raw["source"] not in SOURCES:
        raise ScenarioError(f"{where}: источник «{raw['source']}» не из набора {', '.join(SOURCES)}")
    return Quantity(float(value), raw["unit"], raw["source"], raw.get("note"))


def optional_quantity(raw, kind: str, where: str) -> Quantity | None:
    """An absent optional quality stays None and later blocks the plan as unknown."""
    return None if raw is None else quantity(raw, kind, where)


@dataclass(frozen=True)
class Horizon:
    hours: float
    step_minutes: int

    @property
    def steps(self) -> int:
        return int(round(self.hours * 60 / self.step_minutes))

    def times_hours(self) -> list[float]:
        return [i * self.step_minutes / 60 for i in range(self.steps + 1)]


@dataclass(frozen=True)
class Tank:
    """A blending component with a finite inventory and its own declared properties."""

    tank_id: str
    name: str
    available: bool
    inventory: Quantity
    max_outflow: Quantity
    inflow: Quantity
    cost_per_t: Quantity
    properties: dict[str, Quantity | None]
    note: str | None = None

    def property_value(self, name: str) -> float | None:
        q = self.properties.get(name)
        return None if q is None else q.value

    def to_dict(self) -> dict:
        return {"tank_id": self.tank_id, "name": self.name, "available": self.available,
                "inventory": self.inventory.to_dict(), "max_outflow": self.max_outflow.to_dict(),
                "inflow": self.inflow.to_dict(), "cost_per_t": self.cost_per_t.to_dict(),
                "properties": {k: (v.to_dict() if v else None) for k, v in self.properties.items()},
                "note": self.note}


@dataclass(frozen=True)
class ProductSpec:
    """Declared product limits. A None limit is unknown, which is not the same as no limit."""

    limits: dict[str, Quantity | None]

    def limit_value(self, name: str) -> float | None:
        q = self.limits.get(name)
        return None if q is None else q.value

    def unknown_limits(self) -> list[str]:
        return [name for name in QUALITIES if self.limits.get(name) is None]

    def to_dict(self) -> dict:
        return {k: (v.to_dict() if v else None) for k, v in self.limits.items()}


@dataclass(frozen=True)
class Additive:
    """Cetane additive. Its dose response is our assumption, not a supplied curve."""

    max_dose_fraction: Quantity
    price_per_t: Quantity
    cetane_gain_per_dose_pct: Quantity | None
    affects: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"max_dose_fraction": self.max_dose_fraction.to_dict(),
                "price_per_t": self.price_per_t.to_dict(),
                "cetane_gain_per_dose_pct": (self.cetane_gain_per_dose_pct.to_dict()
                                             if self.cetane_gain_per_dose_pct else None),
                "affects": list(self.affects)}


@dataclass(frozen=True)
class Stage:
    """Controls of one process stage with their declared ranges and response lag."""

    stage_id: str
    controls: dict[str, dict]
    response_lag_hours: Quantity
    model: dict

    def control_range(self, name: str) -> tuple[float, float]:
        spec = self.controls[name]
        return spec["min"].value, spec["max"].value

    def to_dict(self) -> dict:
        return {"stage_id": self.stage_id, "response_lag_hours": self.response_lag_hours.to_dict(),
                "controls": {name: {k: (v.to_dict() if isinstance(v, Quantity) else v)
                                    for k, v in spec.items()} for name, spec in self.controls.items()},
                "model": self.model}


@dataclass(frozen=True)
class CurrentOperation:
    """The blend and throughput running right now. Without it, "keep the regime" is undefined."""

    recipe: dict[str, float]
    throughput: Quantity

    def to_dict(self) -> dict:
        return {"recipe": dict(self.recipe), "throughput": self.throughput.to_dict()}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    description: str
    kind: str
    horizon: Horizon
    crude: dict[str, Quantity]
    stages: dict[str, Stage]
    product: ProductSpec
    tanks: tuple[Tank, ...]
    current_operation: CurrentOperation
    additive: Additive | None
    economics: dict[str, Quantity]
    policy: dict
    assumptions: tuple[str, ...]
    expected: dict = field(default_factory=dict)

    def tank(self, tank_id: str) -> Tank:
        for t in self.tanks:
            if t.tank_id == tank_id:
                return t
        raise ScenarioError(f"Резервуар {tank_id} не описан в сценарии")

    def available_tanks(self) -> tuple[Tank, ...]:
        return tuple(t for t in self.tanks if t.available)

    def unknown_properties(self) -> dict[str, list[str]]:
        """Qualities a tank does not declare. These make the blend result unknown, not compliant."""
        return {t.tank_id: [q for q in QUALITIES if t.properties.get(q) is None] for t in self.tanks}

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "id": self.scenario_id, "title": self.title,
            "description": self.description, "kind": self.kind,
            "horizon": {"hours": self.horizon.hours, "step_minutes": self.horizon.step_minutes},
            "crude": {k: v.to_dict() for k, v in self.crude.items()},
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "product": self.product.to_dict(),
            "tanks": [t.to_dict() for t in self.tanks],
            "current_operation": self.current_operation.to_dict(),
            "additive": self.additive.to_dict() if self.additive else None,
            "economics": {k: v.to_dict() for k, v in self.economics.items()},
            "policy": self.policy,
            "assumptions": list(self.assumptions),
            "expected": self.expected,
        }


CRUDE_KINDS = {"sulfur_wt_pct": "sulfur_wt_pct", "density_kgm3": "density_kgm3", "flow_tph": "flow_tph"}

CONTROL_KINDS = {
    "crude_feed_rate_tph": "flow_tph",
    "avt_furnace_outlet_temp_c": "temperature_c",
    "avt_column_top_temp_c": "temperature_c",
    "avt_column_pressure_mpa_abs": "pressure_mpa",
    "avt_diesel_flow_tph": "flow_tph",
    "ht_feed_flow_m3h": "volume_flow_m3h",
    "ht_pressure_mpa": "pressure_mpa",
    "ht_reactor_inlet_temp_c": "temperature_c",
}

ECONOMICS_KINDS = {
    "diesel_price_per_t": "cost_per_t",
    "treating_cost_per_t_at_reference": "cost_per_t",
    "treating_cost_per_extra_degree_per_t": "cost_per_t",
}

QUALITY_KINDS = {"sulfur_mgkg": "sulfur_mgkg", "t95_c": "t95_c", "cetane_number": "cetane_number"}


def _require(raw: dict, key: str, where: str):
    if key not in raw:
        raise ScenarioError(f"{where}: отсутствует обязательный раздел «{key}»")
    return raw[key]


def _parse_horizon(raw: dict) -> Horizon:
    hours, step = raw.get("hours"), raw.get("step_minutes")
    if not _finite(hours) or not 0 < hours <= 3:
        raise ScenarioError(f"horizon.hours: горизонт должен быть в пределах (0, 3] часов по уточнению "
                            f"эксперта, получено {hours!r}")
    if not isinstance(step, int) or step <= 0:
        raise ScenarioError(f"horizon.step_minutes: шаг должен быть целым положительным числом минут, получено {step!r}")
    total = hours * 60
    if abs(total / step - round(total / step)) > 1e-9:
        raise ScenarioError(f"horizon: шаг {step} мин не делит горизонт {hours} ч нацело")
    return Horizon(float(hours), step)


def _parse_tank(raw: dict, index: int) -> Tank:
    where = f"tanks[{index}]"
    for key in ("tank_id", "name", "available"):
        if key not in raw:
            raise ScenarioError(f"{where}: отсутствует поле «{key}»")
    if not isinstance(raw["available"], bool):
        raise ScenarioError(f"{where}.available: ожидается true или false")
    inventory = quantity(_require(raw, "inventory", where), "mass_t", f"{where}.inventory")
    max_outflow = quantity(_require(raw, "max_outflow", where), "flow_tph", f"{where}.max_outflow")
    inflow = quantity(raw.get("inflow", {"value": 0.0, "unit": "т/ч", "source": "scenario"}),
                      "flow_tph", f"{where}.inflow")
    cost = quantity(_require(raw, "cost_per_t", where), "cost_per_t", f"{where}.cost_per_t")
    if max_outflow.value <= 0 and raw["available"]:
        raise ScenarioError(f"{where}.max_outflow: доступный резервуар с нулевым пределом отбора бессмыслен")
    props_raw = raw.get("properties", {})
    unknown = set(props_raw) - set(QUALITY_KINDS)
    if unknown:
        raise ScenarioError(f"{where}.properties: неизвестные свойства {', '.join(sorted(unknown))}")
    properties = {name: optional_quantity(props_raw.get(name), kind, f"{where}.properties.{name}")
                  for name, kind in QUALITY_KINDS.items()}
    if properties["sulfur_mgkg"] is None:
        raise ScenarioError(f"{where}.properties.sulfur_mgkg: сера компонента обязательна, "
                            f"иначе материальный баланс по жёсткому ограничению не считается")
    return Tank(raw["tank_id"], raw["name"], raw["available"], inventory, max_outflow, inflow,
                cost, properties, raw.get("note"))


def _parse_stage(stage_id: str, raw: dict) -> Stage:
    where = f"stages.{stage_id}"
    lag = quantity(_require(raw, "response_lag_hours", where), "hours", f"{where}.response_lag_hours")
    if not 0 <= lag.value <= 3:
        raise ScenarioError(f"{where}.response_lag_hours: запаздывание должно быть в пределах 0–3 часов "
                            f"по уточнению эксперта, получено {lag.value}")
    controls = {}
    for name, spec in (raw.get("controls") or {}).items():
        kind = CONTROL_KINDS.get(name)
        if kind is None:
            raise ScenarioError(f"{where}.controls.{name}: переменной нет в карте управляющих "
                                f"параметров config/parameters.json")
        low = quantity(_require(spec, "min", f"{where}.controls.{name}"), kind, f"{where}.controls.{name}.min")
        high = quantity(_require(spec, "max", f"{where}.controls.{name}"), kind, f"{where}.controls.{name}.max")
        current = quantity(_require(spec, "current", f"{where}.controls.{name}"), kind,
                           f"{where}.controls.{name}.current")
        if not low.value <= current.value <= high.value:
            raise ScenarioError(f"{where}.controls.{name}: текущее значение {current.value} вне "
                                f"заданного диапазона [{low.value}, {high.value}]")
        step = spec.get("step")
        controls[name] = {"min": low, "max": high, "current": current,
                          "step": quantity(step, kind, f"{where}.controls.{name}.step") if step else None}
    return Stage(stage_id, controls, lag, raw.get("model", {}))


def parse_scenario(raw: dict) -> Scenario:
    if raw.get("schema") != SCHEMA:
        raise ScenarioError(f"Ожидается схема «{SCHEMA}», получено «{raw.get('schema')}»")
    kind = raw.get("kind")
    if kind != "synthetic_blending_scenario":
        raise ScenarioError("kind: сценарий обязан быть явно помечен как synthetic_blending_scenario; "
                            "данных по смешению завод не выдавал")
    for key in ("id", "title", "description"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ScenarioError(f"{key}: обязательное непустое текстовое поле")

    horizon = _parse_horizon(_require(raw, "horizon", "scenario"))

    crude_raw = _require(raw, "crude", "scenario")
    crude = {name: quantity(_require(crude_raw, name, "crude"), kind_, f"crude.{name}")
             for name, kind_ in CRUDE_KINDS.items()}

    stages_raw = _require(raw, "stages", "scenario")
    for required in ("avt", "hydrotreating"):
        if required not in stages_raw:
            raise ScenarioError(f"stages: отсутствует участок «{required}»")
    stages = {sid: _parse_stage(sid, spec) for sid, spec in stages_raw.items()}

    product_raw = _require(raw, "product", "scenario")
    unknown = set(product_raw) - set(QUALITY_KINDS)
    if unknown:
        raise ScenarioError(f"product: неизвестные показатели {', '.join(sorted(unknown))}")
    limits = {name: optional_quantity(product_raw.get(name), kind_, f"product.{name}")
              for name, kind_ in QUALITY_KINDS.items()}
    if limits["sulfur_mgkg"] is None:
        raise ScenarioError("product.sulfur_mgkg: предел серы обязателен, это жёсткое требование ТЗ")
    if limits["sulfur_mgkg"].value > 10.0 + 1e-9:
        raise ScenarioError(f"product.sulfur_mgkg: предел {limits['sulfur_mgkg'].value} мг/кг мягче "
                            f"требования ТЗ 10 мг/кг; ослаблять жёсткое ограничение сценарием нельзя")
    product = ProductSpec(limits)

    tanks_raw = _require(raw, "tanks", "scenario")
    if not isinstance(tanks_raw, list) or len(tanks_raw) < 2:
        raise ScenarioError("tanks: нужно не менее двух резервуаров с разными свойствами "
                            "(требование эксперта, сообщение 517)")
    tanks = tuple(_parse_tank(t, i) for i, t in enumerate(tanks_raw))
    ids = [t.tank_id for t in tanks]
    if len(set(ids)) != len(ids):
        raise ScenarioError("tanks: идентификаторы резервуаров повторяются")
    if not any(t.available for t in tanks):
        raise ScenarioError("tanks: ни один резервуар не доступен, смешение невозможно в принципе")
    if len({t.property_value("sulfur_mgkg") for t in tanks}) == 1:
        raise ScenarioError("tanks: все резервуары имеют одинаковую серу; сценарий не проверяет смешение")

    operation_raw = _require(raw, "current_operation", "scenario")
    recipe = operation_raw.get("recipe")
    if not isinstance(recipe, dict) or not recipe:
        raise ScenarioError("current_operation.recipe: текущий рецепт обязателен, иначе "
                            "сохранение режима не определено")
    unknown_tanks = set(recipe) - {t.tank_id for t in tanks}
    if unknown_tanks:
        raise ScenarioError(f"current_operation.recipe: неизвестные резервуары "
                            f"{', '.join(sorted(unknown_tanks))}")
    total_share = sum(recipe.values())
    if abs(total_share - 1.0) > 1e-6:
        raise ScenarioError(f"current_operation.recipe: доли дают {total_share:.6f}, требуется 1.0")
    current_operation = CurrentOperation(
        {k: float(v) for k, v in recipe.items()},
        quantity(_require(operation_raw, "throughput", "current_operation"), "flow_tph",
                 "current_operation.throughput"))

    additive = None
    if raw.get("additive") is not None:
        a = raw["additive"]
        dose = quantity(_require(a, "max_dose_fraction", "additive"), "fraction", "additive.max_dose_fraction")
        if dose.value > 0.03 + 1e-9:
            raise ScenarioError(f"additive.max_dose_fraction: {dose.value} превышает названные экспертом 3%")
        affects = tuple(a.get("affects", ()))
        if "sulfur_mgkg" in affects:
            raise ScenarioError("additive.affects: присадке нельзя приписывать удаление серы")
        additive = Additive(dose, quantity(_require(a, "price_per_t", "additive"), "cost_per_t", "additive.price_per_t"),
                            optional_quantity(a.get("cetane_gain_per_dose_pct"), "cetane_number",
                                              "additive.cetane_gain_per_dose_pct"),
                            affects)

    econ_raw = _require(raw, "economics", "scenario")
    economics = {name: quantity(_require(econ_raw, name, "economics"), kind_, f"economics.{name}")
                 for name, kind_ in ECONOMICS_KINDS.items()}

    assumptions = tuple(raw.get("assumptions", ()))
    if not assumptions:
        raise ScenarioError("assumptions: сценарий обязан перечислить свои допущения явным текстом")

    return Scenario(raw["id"], raw["title"], raw["description"], kind, horizon, crude, stages,
                    product, tanks, current_operation, additive, economics, raw.get("policy", {}),
                    assumptions, raw.get("expected", {}))


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    if not path.exists():
        raise ScenarioError(f"Файл сценария не найден: {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"{path}: некорректный JSON — {exc}") from exc
    try:
        return parse_scenario(raw)
    except ScenarioError as exc:
        raise ScenarioError(f"{path}: {exc}") from exc


def describe(scenario: Scenario) -> dict:
    """Short human summary used by reports and the future interface."""
    missing = {tank: props for tank, props in scenario.unknown_properties().items() if props}
    return {
        "id": scenario.scenario_id,
        "title": scenario.title,
        "kind": scenario.kind,
        "horizon_hours": scenario.horizon.hours,
        "steps": scenario.horizon.steps,
        "tanks": [t.tank_id for t in scenario.tanks],
        "available_tanks": [t.tank_id for t in scenario.available_tanks()],
        "total_inventory_t": sum(t.inventory.value for t in scenario.available_tanks()),
        "unknown_product_limits": scenario.product.unknown_limits(),
        "tanks_with_unknown_properties": missing,
        "assumptions": list(scenario.assumptions),
        "scope": "Все параметры смешения, резервуаров, цен и откликов заданы для эксперимента "
                 "и не получены из данных завода.",
    }
