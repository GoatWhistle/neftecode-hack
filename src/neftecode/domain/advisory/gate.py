from neftecode.domain.advisory.entities import CheckResult, GateResult, TrajectoryPoint
from neftecode.domain.shared.primitives import FAIL, PASS, UNKNOWN, PRODUCT_LIMITS, _finite
from neftecode.domain.production.scenario import Scenario

MAX_TRUSTED_STEP_HOURS = 1.0




def quality_checks(step: TrajectoryPoint, scenario: Scenario) -> list[CheckResult]:
    checks = []
    for quality, (prop, direction) in PRODUCT_LIMITS.items():
        limit = scenario.product.limit_value(quality)
        value = step.qualities.get(prop)
        constraint = f"quality.{quality}"
        if limit is None:
            checks.append(CheckResult(constraint, UNKNOWN, value, None, step.time_hours,
                                      reason=f"Предел {quality} не задан: условие не проверено"))
            continue
        if value is None or not _finite(value):
            checks.append(CheckResult(constraint, UNKNOWN, None, limit, step.time_hours,
                                      reason=f"Значение {prop} для смеси неизвестно"))
            continue
        ok = value <= limit + 1e-9 if direction == "max" else value >= limit - 1e-9
        checks.append(CheckResult(
            constraint, PASS if ok else FAIL, value, limit, step.time_hours,
            reason="" if ok else f"{prop} = {value:.3f} нарушает предел {'' if quality == prop else quality + ' '}{limit:g} "
                                 f"на {step.time_hours:g} ч"))
    return checks


def control_checks(step: TrajectoryPoint, scenario: Scenario) -> list[CheckResult]:
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


def recipe_checks(step: TrajectoryPoint, scenario: Scenario) -> list[CheckResult]:
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


def inventory_checks(step: TrajectoryPoint, scenario: Scenario) -> list[CheckResult]:
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
        if scenario.tank_park is not None and tank_id == scenario.tank_park.component_tank_id:
            continue
        rate = step.throughput_tph * fraction
        limit = tank.max_outflow.value
        ok = rate <= limit + 1e-9
        checks.append(CheckResult(f"outflow.{tank_id}", PASS if ok else FAIL, rate, limit,
                                  step.time_hours,
                                  reason="" if ok else f"Отбор {rate:.2f} т/ч из {tank_id} выше "
                                                       f"предела {limit:.2f} т/ч на {step.time_hours:g} ч"))
    return checks


def _correctable_sulfur(sulfur: float, throughput_tph: float, scenario: Scenario) -> float | None:
    """Best sulfur attainable when the forecast batch is eventually blended.

    The filling batch is not the stream currently sent to product.  Still, Gate must
    reject a batch forecast that cannot be corrected even with all declared lower-sulfur
    components.  This keeps the warning pre-emptive without pretending that fresh inflow
    instantly changes an already passported draining batch.
    """
    if not _finite(throughput_tph) or throughput_tph <= 0:
        return None
    remaining = 1.0
    result = 0.0
    alternatives = []
    component = scenario.tank_park.component_tank_id if scenario.tank_park else None
    for tank in scenario.tanks:
        value = tank.property_value("sulfur_mgkg")
        if tank.tank_id == component or not tank.available or value is None or value >= sulfur:
            continue
        alternatives.append((value, max(0.0, tank.max_outflow.value / throughput_tph)))
    for value, capacity_fraction in sorted(alternatives):
        fraction = min(remaining, capacity_fraction)
        result += fraction * value
        remaining -= fraction
        if remaining <= 1e-12:
            break
    return result + remaining * sulfur


def park_checks(step: TrajectoryPoint, scenario: Scenario) -> list[CheckResult]:
    if step.park is None:
        return []
    park = step.park
    if not isinstance(park, dict):
        return [CheckResult("park.contract", UNKNOWN, None, None, step.time_hours,
                            reason="Траектория парка имеет неизвестный формат")]
    checks = []
    model = park.get("model_version")
    checks.append(CheckResult("park.model_version", PASS if isinstance(model, str) and model else UNKNOWN,
                              None, None, step.time_hours,
                              reason="" if isinstance(model, str) and model else "Версия модели парка не указана"))
    balance = park.get("balance_error_t")
    if not _finite(balance):
        checks.append(CheckResult("park.balance", UNKNOWN, None, 0.0, step.time_hours,
                                  reason="Массовый баланс парка не рассчитан"))
    else:
        ok = abs(balance) <= 1e-6
        checks.append(CheckResult("park.balance", PASS if ok else FAIL, abs(balance), 0.0, step.time_hours,
                                  reason="" if ok else f"Ошибка массового баланса парка {balance:.6f} т"))
    tanks = park.get("tanks")
    if not isinstance(tanks, list) or not tanks:
        checks.append(CheckResult("park.tanks", UNKNOWN, None, None, step.time_hours,
                                  reason="Состояния резервуаров не переданы"))
        return checks
    for raw in tanks:
        if not isinstance(raw, dict) or not isinstance(raw.get("tank_id"), str):
            checks.append(CheckResult("park.tank.contract", UNKNOWN, None, None, step.time_hours,
                                      reason="Состояние резервуара имеет неизвестный формат"))
            continue
        tank_id = raw["tank_id"]
        mass, capacity = raw.get("mass_t"), raw.get("capacity_t")
        if not _finite(mass) or not _finite(capacity):
            checks.append(CheckResult(f"park.{tank_id}.capacity", UNKNOWN, None, None, step.time_hours,
                                      reason=f"Масса или вместимость {tank_id} неизвестна"))
        else:
            ok = -1e-9 <= mass <= capacity + 1e-9
            checks.append(CheckResult(f"park.{tank_id}.capacity", PASS if ok else FAIL, mass, capacity,
                                      step.time_hours, reason="" if ok else
                                      f"Масса {tank_id} {mass:.3f} т вне диапазона [0, {capacity:.3f}]"))
        status = raw.get("status")
        if status not in {"available", "filling", "awaiting_passport", "ready", "draining"}:
            checks.append(CheckResult(f"park.{tank_id}.status", UNKNOWN, None, None, step.time_hours,
                                      reason=f"Стадия резервуара {tank_id} неизвестна"))
        elif status in {"ready", "draining"}:
            properties = raw.get("properties")
            if not isinstance(properties, dict) or any(properties.get(name) is None
                                                       for name in ("sulfur_mgkg", "t95_c",
                                                                    "cetane_number", "density_kgm3")):
                checks.append(CheckResult(f"park.{tank_id}.passport", UNKNOWN, None, None, step.time_hours,
                                          reason=f"Паспорт партии {tank_id} содержит неизвестные свойства"))
            else:
                checks.append(CheckResult(f"park.{tank_id}.passport", PASS, None, None, step.time_hours))
        if status in {"filling", "awaiting_passport"}:
            properties = raw.get("properties")
            sulfur = properties.get("sulfur_mgkg") if isinstance(properties, dict) else None
            limit = scenario.product.limit_value("sulfur_mgkg")
            corrected = (_correctable_sulfur(sulfur, step.throughput_tph, scenario)
                         if _finite(sulfur) and limit is not None else None)
            constraint = f"park.{tank_id}.passport_forecast.sulfur_mgkg"
            if corrected is None:
                checks.append(CheckResult(
                    constraint, UNKNOWN, None, limit, step.time_hours,
                    reason=f"Прогноз паспорта наливаемой партии {tank_id} не рассчитан"))
            else:
                ok = corrected <= limit + 1e-9
                checks.append(CheckResult(
                    constraint, PASS if ok else FAIL, corrected, limit, step.time_hours,
                    reason="" if ok else
                    f"Прогноз серы партии {tank_id} после максимально доступной коррекции "
                    f"{corrected:.3f} мг/кг выше предела {limit:g} мг/кг"))
            for name in ("t95_c", "cetane_number", "density_kgm3"):
                value = properties.get(name) if isinstance(properties, dict) else None
                known = _finite(value)
                checks.append(CheckResult(
                    f"park.{tank_id}.passport_forecast.{name}.known",
                    PASS if known else UNKNOWN, value if known else None, None, step.time_hours,
                    reason="" if known else
                    f"Для прогноза паспорта наливаемой партии {tank_id} неизвестно свойство {name}"))
        uncertainty = raw.get("initial_uncertainty")
        if uncertainty:
            checks.append(CheckResult(f"park.{tank_id}.initial_state", UNKNOWN, None, None, step.time_hours,
                                      reason=f"Начальное состояние {tank_id} неизвестно: "
                                             + ", ".join(map(str, uncertainty))))
    for reason in park.get("reasons", ()):
        checks.append(CheckResult("park.transition", FAIL, None, None, step.time_hours, reason=str(reason)))
    return checks


def applicability_check(step: TrajectoryPoint) -> CheckResult:
    if step.applicability == "in_region":
        return CheckResult("model.applicability", PASS, None, None, step.time_hours)
    return CheckResult("model.applicability", UNKNOWN, None, None, step.time_hours,
                       reason=f"Режим вне области применимости модели на {step.time_hours:g} ч: "
                              f"последствия не описаны")


def discretisation_check(steps, horizon_hours: float) -> CheckResult:
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


def throughput_check(step: TrajectoryPoint) -> CheckResult:
    if not _finite(step.throughput_tph) or step.throughput_tph < 0:
        return CheckResult("throughput", UNKNOWN, None, 0.0, step.time_hours,
                           reason="Выпуск должен быть конечным и неотрицательным")
    return CheckResult("throughput", PASS, step.throughput_tph, 0.0, step.time_hours)


def check_plan(plan_id: str, steps, scenario: Scenario,
               terminal: dict | None = None) -> GateResult:
    steps = list(steps)
    checks: list[CheckResult] = []
    checks.append(time_grid_check(steps, scenario))
    for step in steps:
        checks.extend(quality_checks(step, scenario))
        checks.extend(control_checks(step, scenario))
        checks.extend(recipe_checks(step, scenario))
        checks.append(throughput_check(step))
        checks.extend(inventory_checks(step, scenario))
        checks.extend(park_checks(step, scenario))
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
