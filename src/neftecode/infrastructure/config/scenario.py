"""Внешний адаптер JSON для доменной модели сценария.

Загрузка файлов находится за пределами domain; сами сущности импортируются из production.
"""
import json
from pathlib import Path

from neftecode.domain.shared.primitives import QUALITIES  # noqa: F401 - re-exported for callers
from neftecode.domain.production.scenario import (
    SCHEMA,
    Additive,
    ControlActuation,
    CurrentOperation,
    Horizon,
    ProductSpec,
    Scenario,
    ScenarioError,
    Stage,
    Tank,
    _finite,
    optional_quantity,
    quantity,
)

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

QUALITY_KINDS = {"sulfur_mgkg": "sulfur_mgkg", "t95_c": "t95_c", "cetane_number": "cetane_number",
                 "density_kgm3": "density_kgm3"}

PRODUCT_KINDS = {"sulfur_mgkg": "sulfur_mgkg", "t95_c": "t95_c", "cetane_number": "cetane_number",
                 "density_min_kgm3": "density_kgm3", "density_max_kgm3": "density_kgm3"}


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
    from_chain = raw.get("sulfur_from_chain", False)
    if not isinstance(from_chain, bool):
        raise ScenarioError(f"{where}.sulfur_from_chain: ожидается true или false")
    if from_chain and properties["sulfur_mgkg"].source in ("derived", "measured"):
        raise ScenarioError(f"{where}: сера не может одновременно приходить из модели цепочки "
                            f"и из выведенного измерения")
    inflow_sulfur = optional_quantity(raw.get("inflow_sulfur_mgkg"), "sulfur_mgkg", f"{where}.inflow_sulfur_mgkg")
    if inflow_sulfur is not None and from_chain:
        raise ScenarioError(f"{where}: сера притока не может одновременно приходить из модели цепочки "
                            f"и из прогноза по измерениям")
    return Tank(raw["tank_id"], raw["name"], raw["available"], inventory, max_outflow, inflow,
                cost, properties, raw.get("note"), from_chain, inflow_sulfur)


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
        raw_actuation = spec.get("actuation")
        if not isinstance(raw_actuation, dict):
            raise ScenarioError(f"{where}.controls.{name}.actuation: не описано, как исполняется изменение "
                                f"(регулятор с обратной связью, контур, тег)")
        try:
            actuation = ControlActuation(raw_actuation.get("kind"), raw_actuation.get("loop"),
                                         raw_actuation.get("measured_tag"), raw_actuation.get("source"),
                                         raw_actuation.get("note", ""))
        except ScenarioError as exc:
            raise ScenarioError(f"{where}.controls.{name}.{exc}") from exc
        controls[name] = {"min": low, "max": high, "current": current,
                          "step": quantity(step, kind, f"{where}.controls.{name}.step") if step else None,
                          "actuation": actuation}
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
    unknown = set(product_raw) - set(PRODUCT_KINDS)
    if unknown:
        raise ScenarioError(f"product: неизвестные показатели {', '.join(sorted(unknown))}")
    limits = {name: optional_quantity(product_raw.get(name), kind_, f"product.{name}")
              for name, kind_ in PRODUCT_KINDS.items()}
    low, high = limits["density_min_kgm3"], limits["density_max_kgm3"]
    if low is not None and high is not None and low.value > high.value:
        raise ScenarioError(f"product.density: нижний предел {low.value} выше верхнего {high.value}")
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


class FileScenarioRepository:
    """Loads validated scenarios from a directory by their stable scenario id."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def get(self, scenario_id: str) -> Scenario:
        path = self.directory / f"{scenario_id}.json"
        if not path.is_file():
            raise ScenarioError(f"Сценарий «{scenario_id}» не найден в {self.directory}")
        scenario = load_scenario(path)
        if scenario.scenario_id != scenario_id:
            raise ScenarioError(f"{path}: id сценария не совпадает с запрошенным «{scenario_id}»")
        return scenario
