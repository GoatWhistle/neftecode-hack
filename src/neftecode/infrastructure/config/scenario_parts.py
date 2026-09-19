from dataclasses import replace

from neftecode.domain.production.scenario import (
    ControlActuation,
    Horizon,
    Quantity,
    ScenarioError,
    Stage,
    Tank,
    _finite,
    optional_quantity,
    quantity,
)
from neftecode.domain.production.economics import deep_treating_depth_mgkg, on_demand_price_per_t


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
    "deep_treating_reference_mgkg": "sulfur_mgkg",
    "deep_treating_cost_per_ppm2_per_t": "cost_per_ppm2_per_t",
    "sulfur_depth_per_degree_mgkg": "sulfur_per_degree",
    "offspec_rework_cost_share": "fraction",
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


def _production_number(raw: dict, key: str, where: str, default):
    declared = raw.get(key)
    if declared is None:
        if default is None:
            return None
        return default
    if isinstance(declared, dict):
        declared = declared.get("value")
    if not isinstance(declared, (int, float)) or isinstance(declared, bool) or declared < 0:
        raise ScenarioError(f"{where}.{key}: ожидается неотрицательное число")
    return float(declared)


def _parse_tank(raw: dict, index: int) -> Tank:
    where = f"tanks[{index}]"
    for key in ("tank_id", "name", "available"):
        if key not in raw:
            raise ScenarioError(f"{where}: отсутствует поле «{key}»")
    if not isinstance(raw["available"], bool):
        raise ScenarioError(f"{where}.available: ожидается true или false")
    on_demand = raw.get("on_demand", False)
    if not isinstance(on_demand, bool):
        raise ScenarioError(f"{where}.on_demand: ожидается true или false")
    if on_demand:
        for key in ("inventory", "cost_per_t"):
            declared = raw.get(key)
            if declared is None:
                continue
            if not isinstance(declared, dict) or declared.get("source") != "derived":
                raise ScenarioError(f"{where}.{key}: компонент производится по необходимости, "
                                    f"запас и цена не задаются, а выводятся")
        inventory = Quantity(0.0, "т", "derived", "Производится по необходимости: запаса нет")
        cost = Quantity(0.0, "усл.ед./т", "derived", "Выводится из глубины очистки после разбора economics")
        lead_time = _production_number(raw, "production_lead_time_hours", where, default=0.0)
        rate = _production_number(raw, "production_rate_tph", where, default=None)
    else:
        inventory = quantity(_require(raw, "inventory", where), "mass_t", f"{where}.inventory")
        cost = quantity(_require(raw, "cost_per_t", where), "cost_per_t", f"{where}.cost_per_t")
        lead_time = 0.0
        rate = 0.0
    max_outflow = quantity(_require(raw, "max_outflow", where), "flow_tph", f"{where}.max_outflow")
    inflow = quantity(raw.get("inflow", {"value": 0.0, "unit": "т/ч", "source": "scenario"}),
                      "flow_tph", f"{where}.inflow")
    if max_outflow.value <= 0 and raw["available"]:
        raise ScenarioError(f"{where}.max_outflow: доступный резервуар с нулевым пределом отбора бессмыслен")
    if on_demand:
        if rate is None:
            rate = max_outflow.value
        if rate <= 0:
            raise ScenarioError(f"{where}.production_rate_tph: компонент по необходимости "
                                f"с нулевым темпом производства недоступен, а не бесплатен")
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
                cost, properties, raw.get("note"), from_chain, inflow_sulfur, on_demand,
                float(lead_time), float(rate))


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


def _price_on_demand(tank: Tank, economics: dict) -> Tank:
    if not tank.on_demand:
        return tank
    sulfur = tank.property_value("sulfur_mgkg")
    depth = deep_treating_depth_mgkg(economics, sulfur)
    price = on_demand_price_per_t(economics, sulfur)
    reference = economics["deep_treating_reference_mgkg"].value
    return replace(tank, cost_per_t=Quantity(
        round(price, 6), "усл.ед./т", "derived",
        f"ДТ {economics['diesel_price_per_t'].value:g} + очистка в опорном режиме "
        f"{economics['treating_cost_per_t_at_reference'].value:g} + квадрат глубины "
        f"{economics['deep_treating_cost_per_ppm2_per_t'].value:g}·({reference:g} − {sulfur:g})² "
        f"= {price:.4f}; глубина {depth:g} мг/кг ниже {reference:g}. Форма квадрата — ответ "
        f"организаторов 18.09; масштаб — сценарий."))
