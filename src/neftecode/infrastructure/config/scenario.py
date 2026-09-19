import json
from pathlib import Path

from neftecode.domain.shared.primitives import QUALITIES  # noqa: F401 - re-exported for callers
from neftecode.domain.production.scenario import (
    SCHEMA,
    Additive,
    CurrentOperation,
    ProductSpec,
    Scenario,
    ScenarioError,
    optional_quantity,
    quantity,
)
from .scenario_parts import (CONTROL_KINDS, CRUDE_KINDS, ECONOMICS_KINDS, PRODUCT_KINDS, QUALITY_KINDS,
                             _parse_horizon, _parse_stage, _parse_tank, _price_on_demand, _require)

__all__ = ["CONTROL_KINDS", "CRUDE_KINDS", "ECONOMICS_KINDS", "FileScenarioRepository", "PRODUCT_KINDS",
           "QUALITIES", "QUALITY_KINDS", "ScenarioError", "describe", "load_scenario", "parse_scenario"]

_REQUIRED_DEPLOYMENT_INPUTS = {"tank_farm", "deep_treatment_capacity"}


def _validate_deployment_inputs(policy: dict) -> None:
    inputs = policy.get("deployment_inputs")
    if not isinstance(inputs, list):
        raise ScenarioError("policy.deployment_inputs: нужен список внешних параметров промышленного применения")
    ids = set()
    for index, item in enumerate(inputs):
        where = f"policy.deployment_inputs[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ScenarioError(f"{where}.id: обязателен непустой идентификатор")
        if item["id"] in ids:
            raise ScenarioError(f"{where}.id: идентификатор {item['id']} повторяется")
        ids.add(item["id"])
        if item.get("status") not in {"open", "given"}:
            raise ScenarioError(f"{where}.status: ожидается open или given")
        if not isinstance(item.get("label"), str) or not item["label"].strip():
            raise ScenarioError(f"{where}.label: нужно понятное название внешнего параметра")
        if not isinstance(item.get("required_values"), list) or not item["required_values"]:
            raise ScenarioError(f"{where}.required_values: перечислите значения, которые должен дать завод")
        if not isinstance(item.get("scenario_assumptions"), dict):
            raise ScenarioError(f"{where}.scenario_assumptions: явно отделите расчётные допущения")
        if item["status"] == "given":
            values = item.get("values")
            missing_values = set(item["required_values"]) - set(values or {})
            if not isinstance(values, dict) or missing_values:
                raise ScenarioError(f"{where}.values: для status=given нужны все required_values")
    missing = _REQUIRED_DEPLOYMENT_INPUTS - ids
    if missing:
        raise ScenarioError("policy.deployment_inputs: отсутствуют обязательные внешние входы "
                            + ", ".join(sorted(missing)))


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
    tanks = [_price_on_demand(tank, economics) for tank in tanks]

    policy = raw.get("policy", {})
    if not isinstance(policy, dict):
        raise ScenarioError("policy: ожидается объект")
    _validate_deployment_inputs(policy)

    assumptions = tuple(raw.get("assumptions", ()))
    if not assumptions:
        raise ScenarioError("assumptions: сценарий обязан перечислить свои допущения явным текстом")

    return Scenario(raw["id"], raw["title"], raw["description"], kind, horizon, crude, stages,
                    product, tanks, current_operation, additive, economics, policy,
                    assumptions, raw.get("expected", {}))


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    if not path.exists():
        raise ScenarioError(f"Файл сценария не найден: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"{path}: некорректный JSON — {exc}") from exc
    try:
        return parse_scenario(raw)
    except ScenarioError as exc:
        raise ScenarioError(f"{path}: {exc}") from exc


def describe(scenario: Scenario) -> dict:
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
        "deployment_inputs": list(scenario.policy.get("deployment_inputs", ())),
        "assumptions": list(scenario.assumptions),
        "scope": "Все параметры смешения, резервуаров, цен и откликов заданы для эксперимента "
                 "и не получены из данных завода.",
    }


class FileScenarioRepository:

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
