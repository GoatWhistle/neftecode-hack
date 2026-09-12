"""The one place a plan is allowed to be declared acceptable.

Every mandatory condition — product qualities, control ranges, additive dose, tank stocks,
outflow limits, model applicability — is checked at EVERY point of the trajectory and folded
into a single `GateResult`. Feasibility is derived from the checks, never asserted by a caller.

Two properties this module exists to guarantee:

* a plan that is safe only at the end of the horizon does not pass, because the violation is
  recorded at the time it happens;
* `unknown` blocks. A condition that could not be evaluated is not a condition that was met,
  no matter how attractive the plan's economics are.

Discretisation is explicit: the gate sees the points the trajectory was computed at. Between
two checked points nothing is known, so `step_hours` is reported and a coarse grid is flagged
rather than silently trusted.
"""
from dataclasses import dataclass
import math

from .contracts import CheckResult, FAIL, GateResult, PASS, UNKNOWN
from .scenario import QUALITIES, QUALITY_DIRECTION, Scenario

#: Grid finer than this is considered adequate for a 0-3 hour horizon; coarser is flagged.
MAX_TRUSTED_STEP_HOURS = 1.0


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class TrajectoryStep:
    """One checked point of a plan: what the models say holds there."""

    time_hours: float
    qualities: dict[str, float | None]
    controls: dict[str, float]
    inventories: dict[str, float]
    recipe: dict[str, float]
    throughput_tph: float
    additive_dose: float = 0.0
    applicability: str = "in_region"
    inventory_reasons: tuple[str, ...] = ()


def quality_checks(step: TrajectoryStep, scenario: Scenario) -> list[CheckResult]:
    """Compare each product quality with its limit at this point."""
    checks = []
    for quality in QUALITIES:
        limit = scenario.product.limit_value(quality)
        value = step.qualities.get(quality)
        constraint = f"quality.{quality}"
        if limit is None:
            checks.append(CheckResult(constraint, UNKNOWN, value, None, step.time_hours,
                                      reason=f"Предел {quality} не задан: условие не проверено"))
            continue
        if value is None or not _finite(value):
            checks.append(CheckResult(constraint, UNKNOWN, None, limit, step.time_hours,
                                      reason=f"Значение {quality} для смеси неизвестно"))
            continue
        direction = QUALITY_DIRECTION[quality]
        ok = value <= limit + 1e-9 if direction == "max" else value >= limit - 1e-9
        checks.append(CheckResult(
            constraint, PASS if ok else FAIL, value, limit, step.time_hours,
            reason="" if ok else f"{quality} = {value:.3f} нарушает предел {limit:g} "
                                 f"на {step.time_hours:g} ч"))
    return checks


def control_checks(step: TrajectoryStep, scenario: Scenario) -> list[CheckResult]:
    """Every setpoint must stay inside the range the scenario declares for it."""
    checks = []
    declared = set()
    for stage in scenario.stages.values():
        declared.update(stage.controls)
        model = stage.model if isinstance(stage.model, dict) else {}
        optional = set(model.get("optional_controls", ()))
        required = set(model.get("required_controls", stage.controls)) - optional
        for name, spec in stage.controls.items():
            if name not in step.controls:
                if name in required:
                    checks.append(CheckResult(f"control.{name}", UNKNOWN, None, None, step.time_hours,
                                              reason=f"Обязательная уставка {name} отсутствует"))
                continue
            value = step.controls[name]
            low, high = spec["min"].value, spec["max"].value
            constraint = f"control.{name}"
            if not _finite(value):
                checks.append(CheckResult(constraint, UNKNOWN, None, None, step.time_hours,
                                          reason=f"Уставка {name} неизвестна"))
                continue
            ok = low - 1e-9 <= value <= high + 1e-9
            checks.append(CheckResult(
                constraint, PASS if ok else FAIL, value, high, step.time_hours,
                reason="" if ok else f"{name} = {value:g} вне диапазона [{low:g}, {high:g}] "
                                 f"на {step.time_hours:g} ч"))
    for name in set(step.controls) - declared:
        checks.append(CheckResult(f"control.{name}.known", UNKNOWN, step.controls[name], None,
                                  step.time_hours, reason=f"Неизвестная управляющая переменная {name}"))
    return checks


def recipe_checks(step: TrajectoryStep, scenario: Scenario) -> list[CheckResult]:
    """Fractions form a composition, the dose stays within the expert's limit."""
    checks = []
    fractions = step.recipe or {}
    invalid = [name for name, fraction in fractions.items()
               if not _finite(fraction) or fraction < -1e-9]
    if invalid:
        status = UNKNOWN if any(not _finite(fractions[n]) for n in invalid) else FAIL
        checks.append(CheckResult("recipe.non_negative", status, None, 0.0, step.time_hours,
                                  reason=f"Недопустимые доли (конечные и неотрицательные обязательны): {', '.join(invalid)}"))
    total = sum(fractions.values()) if fractions and all(_finite(v) for v in fractions.values()) else None
    if total is None or not _finite(total):
        checks.append(CheckResult("recipe.sum", UNKNOWN, None, 1.0, step.time_hours,
                                  reason="Состав смеси неизвестен"))
    else:
        ok = abs(total - 1.0) <= 1e-6
        checks.append(CheckResult("recipe.sum", PASS if ok else FAIL, total, 1.0, step.time_hours,
                                  reason="" if ok else f"Доли дают {total:.6f} вместо 1.0 "
                                                       f"на {step.time_hours:g} ч"))
    additive = scenario.additive
    dose = step.additive_dose
    if not _finite(dose):
        checks.append(CheckResult("additive.dose", UNKNOWN, None, None, step.time_hours,
                                  reason="Доза присадки неизвестна"))
    elif dose > 0 and additive is None:
        checks.append(CheckResult("additive.dose", FAIL, dose, 0.0, step.time_hours,
                                  reason="Присадка в сценарии не описана, но доза ненулевая"))
    elif additive is not None:
        limit = additive.max_dose_fraction.value
        ok = -1e-12 <= dose <= limit + 1e-12
        checks.append(CheckResult("additive.dose", PASS if ok else FAIL, dose, limit, step.time_hours,
                                  reason="" if ok else f"Доза {dose:.4f} вне допустимых "
                                                       f"[0, {limit:.4f}] на {step.time_hours:g} ч"))
    return checks


def inventory_checks(step: TrajectoryStep, scenario: Scenario) -> list[CheckResult]:
    """Stocks must stay non-negative and outflow limits must hold."""
    checks = []
    inventories = step.inventories or {}
    for tank_id, mass in inventories.items():
        constraint = f"inventory.{tank_id}"
        if mass is None or not _finite(mass):
            checks.append(CheckResult(constraint, UNKNOWN, None, 0.0, step.time_hours,
                                      reason=f"Остаток резервуара {tank_id} неизвестен"))
            continue
        ok = mass >= -1e-9
        checks.append(CheckResult(constraint, PASS if ok else FAIL, mass, 0.0, step.time_hours,
                                  reason="" if ok else f"Отрицательный остаток {tank_id} "
                                                       f"на {step.time_hours:g} ч"))
    for reason in step.inventory_reasons:
        checks.append(CheckResult("inventory.availability", FAIL, None, None, step.time_hours,
                                  reason=f"{reason} (на {step.time_hours:g} ч)"))
    for tank_id, fraction in (step.recipe or {}).items():
        if not _finite(fraction) or fraction <= 1e-12:
            continue
        if tank_id not in inventories:
            checks.append(CheckResult(f"inventory.{tank_id}.present", UNKNOWN, None, None, step.time_hours,
                                      reason=f"Остаток используемого резервуара {tank_id} отсутствует"))
            continue
        try:
            tank = scenario.tank(tank_id)
        except Exception:
            checks.append(CheckResult(f"inventory.{tank_id}.known", FAIL, None, None, step.time_hours,
                                      reason=f"Резервуар {tank_id} не описан в сценарии"))
            continue
        if not tank.available:
            checks.append(CheckResult(f"inventory.{tank_id}.available", FAIL, None, None,
                                      step.time_hours,
                                      reason=f"Резервуар {tank_id} недоступен на {step.time_hours:g} ч"))
        rate = step.throughput_tph * fraction
        limit = tank.max_outflow.value
        ok = rate <= limit + 1e-9
        checks.append(CheckResult(f"outflow.{tank_id}", PASS if ok else FAIL, rate, limit,
                                  step.time_hours,
                                  reason="" if ok else f"Отбор {rate:.2f} т/ч из {tank_id} выше "
                                                       f"предела {limit:.2f} т/ч на {step.time_hours:g} ч"))
    return checks


def applicability_check(step: TrajectoryStep) -> CheckResult:
    """A result produced outside the model's declared region cannot support a recommendation."""
    if step.applicability == "in_region":
        return CheckResult("model.applicability", PASS, None, None, step.time_hours)
    return CheckResult("model.applicability", UNKNOWN, None, None, step.time_hours,
                       reason=f"Режим вне области применимости модели на {step.time_hours:g} ч: "
                              f"последствия не описаны")


def discretisation_check(steps, horizon_hours: float) -> CheckResult:
    """Between two checked points nothing is known; say so instead of assuming."""
    times = [s.time_hours for s in steps]
    if not _finite(horizon_hours) or any(not _finite(t) for t in times):
        return CheckResult("plan.discretisation", UNKNOWN, None, None, None,
                           reason="Временная сетка содержит нечисловое или бесконечное время")
    if not times:
        return CheckResult("plan.discretisation", UNKNOWN, None, None, None,
                           reason="План не содержит проверяемых точек")
    gaps = [b - a for a, b in zip(times, times[1:])] + [horizon_hours - times[-1]]
    worst = max(gaps) if gaps else 0.0
    if worst <= MAX_TRUSTED_STEP_HOURS + 1e-9:
        return CheckResult("plan.discretisation", PASS, worst, MAX_TRUSTED_STEP_HOURS, None)
    return CheckResult("plan.discretisation", UNKNOWN, worst, MAX_TRUSTED_STEP_HOURS, None,
                       reason=f"Шаг проверки {worst:g} ч крупнее {MAX_TRUSTED_STEP_HOURS:g} ч: "
                              f"между точками поведение не проверено")


def time_grid_check(steps, scenario: Scenario) -> CheckResult:
    """Require the complete, declared scenario grid from zero through the horizon."""
    times = [s.time_hours for s in steps]
    expected = scenario.horizon.times_hours()
    if (not times or any(not _finite(t) for t in times) or
            times != sorted(times) or len(set(times)) != len(times)):
        return CheckResult("plan.time_grid", UNKNOWN, None, None, None,
                           reason="Временная сетка должна быть конечной, возрастающей и без повторов")
    if times != expected:
        return CheckResult("plan.time_grid", UNKNOWN, float(len(times)), float(len(expected)), None,
                           reason=f"Временная сетка обязана покрывать 0–{scenario.horizon.hours:g} ч "
                                  f"с шагом сценария {scenario.horizon.step_minutes} мин без дыр")
    return CheckResult("plan.time_grid", PASS, len(times), len(expected), None)


def throughput_check(step: TrajectoryStep) -> CheckResult:
    if not _finite(step.throughput_tph) or step.throughput_tph < 0:
        return CheckResult("throughput", UNKNOWN, None, 0.0, step.time_hours,
                           reason="Выпуск должен быть конечным и неотрицательным")
    return CheckResult("throughput", PASS, step.throughput_tph, 0.0, step.time_hours)


def check_plan(plan_id: str, steps, scenario: Scenario,
               terminal: dict | None = None) -> GateResult:
    """Run every mandatory check at every point, plus the terminal and discretisation rules."""
    steps = list(steps)
    checks: list[CheckResult] = []
    checks.append(time_grid_check(steps, scenario))
    for step in steps:
        checks.extend(quality_checks(step, scenario))
        checks.extend(control_checks(step, scenario))
        checks.extend(recipe_checks(step, scenario))
        checks.append(throughput_check(step))
        checks.extend(inventory_checks(step, scenario))
        checks.append(applicability_check(step))
    checks.append(discretisation_check(steps, scenario.horizon.hours))
    terminal_rule = (scenario.policy or {}).get("terminal_inventory_rule", "none")
    if terminal_rule != "none" and terminal is None:
        checks.append(CheckResult("inventory.terminal", UNKNOWN, None, None,
                                  scenario.horizon.hours,
                                  reason=f"Активное правило конечного остатка «{terminal_rule}» не проверено"))
    elif terminal is not None:
        valid_terminal = isinstance(terminal, dict) and isinstance(terminal.get("satisfied"), bool)
        checks.append(CheckResult(
            "inventory.terminal", PASS if valid_terminal and terminal.get("satisfied") else (FAIL if valid_terminal else UNKNOWN), None, None,
            scenario.horizon.hours,
            reason="" if valid_terminal and terminal.get("satisfied") else
                   (f"Запас на конце горизонта: {terminal.get('reason', 'недостаточен')}" if valid_terminal
                    else "Результат проверки конечного остатка недостоверен")))
    if not checks:
        checks.append(CheckResult("plan.empty", FAIL, None, None, None,
                                  reason="План не содержит ни одной проверки"))
    return GateResult(plan_id, tuple(checks))
