from neftecode.domain.production.scenario import Scenario, Stage

from .explain_types import _finite

LIVE, SCENARIO = "live", "scenario"

SCENARIO_MODEL = "scenario"
DATA_BETA = "data_beta"
SCENARIO_KINETICS = "scenario_kinetics"
MASS_BALANCE = "mass_balance"

LABELS = {"avt": "АВТ", "hydrotreating": "Гидроочистка", "blending": "Смешение"}


def chain_mode(scenario: Scenario) -> str:
    # Пометку оставляет только привязка live-измерений (binding.bind_measurements); в сценарии её нет.
    return LIVE if scenario.policy.get("disabled_control_moves_note") else SCENARIO


def _movable(scenario: Scenario, stage: Stage) -> dict[str, bool]:
    # Та же отсечка, что у перебора ходов в optimizer._control_options: ход отключён политикой,
    # нет шага или коридор min..max вырожден — такую уставку советчик не двигает.
    disabled = set(scenario.policy.get("disabled_control_moves") or ())
    out = {}
    for name, spec in sorted(stage.controls.items()):
        step = spec["step"].value if spec.get("step") else 0.0
        low, high = spec["min"].value, spec["max"].value
        out[name] = name not in disabled and _finite(step) and step > 0 and high - low > 1e-9
    return out


def _stage_reason(scenario: Scenario, controls: dict[str, bool], mode: str) -> str:
    disabled = set(scenario.policy.get("disabled_control_moves") or ())
    if any(controls.values()):
        moving = ", ".join(name for name, ok in controls.items() if ok)
        return f"советчик перебирает ходы уставок: {moving}"
    if controls and all(name in disabled for name in controls):
        return (scenario.policy.get("disabled_control_moves_note")
                or "ходы этого блока отключены политикой сценария")
    if mode == LIVE:
        return "числовая уставка не предлагается: вне области отклика по данным или нет измерения"
    return "у уставок блока нет шага или коридор min..max вырожден"


def _avt(scenario: Scenario, mode: str) -> dict:
    stage = scenario.stages["avt"]
    controls = _movable(scenario, stage)
    return {"id": "avt", "label": LABELS["avt"], "controllable": any(controls.values()),
            "controllable_reason": _stage_reason(scenario, controls, mode), "controls": controls,
            "model_basis": SCENARIO_MODEL,
            "model_basis_note": ("сценарная линейная модель с заданными коэффициентами; отклик установки "
                                 "по данным не измерен, эффект из данных АВТ не приписывается")}


def _hydrotreating(scenario: Scenario, mode: str) -> dict:
    stage = scenario.stages["hydrotreating"]
    controls = _movable(scenario, stage)
    model = stage.model or {}
    beta = model.get("beta_mgkg_per_c")
    if model.get("provenance") == "derived" and _finite(beta):
        basis = DATA_BETA
        note = (f"эффект хода T6 — β = {beta:g} мг/кг на °C по данным завода "
                f"({model.get('response_source') or 'модель отклика'}); коэффициент кинетики пересчитан из β (k = −β/S₀)")
    else:
        basis = SCENARIO_KINETICS
        note = "сценарная кинетика с заданными коэффициентами; отклик по данным не применяется"
    block = {"id": "hydrotreating", "label": LABELS["hydrotreating"], "controllable": any(controls.values()),
             "controllable_reason": _stage_reason(scenario, controls, mode), "controls": controls,
             "model_basis": basis, "model_basis_note": note}
    if basis == DATA_BETA:
        block["beta_mgkg_per_c"] = float(beta)
    return block


def _blending(scenario: Scenario) -> dict:
    available = [tank.tank_id for tank in scenario.available_tanks()]
    return {"id": "blending", "label": LABELS["blending"], "controllable": bool(available),
            "controllable_reason": ("советчик перебирает рецепт, выпуск и дозу присадки"
                                    if available else "доступных компонентов нет: смешивать нечего"),
            "controls": {"recipe": bool(available), "throughput_tph": bool(available),
                         "additive_dose": bool(available) and scenario.additive is not None},
            "model_basis": MASS_BALANCE,
            "model_basis_note": ("сера — материальный баланс по массовым долям; T95 и цетановое число — "
                                 "линейное сценарное правило, плотность — аддитивность объёмов")}


def chain_view(scenario: Scenario) -> dict:
    mode = chain_mode(scenario)
    return {"mode": mode, "blocks": [_avt(scenario, mode), _hydrotreating(scenario, mode), _blending(scenario)]}
