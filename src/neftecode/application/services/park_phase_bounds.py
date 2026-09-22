"""Sufficient bounds over the continuous phase interval for tank-park/1.

This is deliberately a certificate, not a completeness claim for the search. If
its assumptions fail, sampling must not turn an unproved plan into a safe one.
"""
import math

from neftecode.domain.advisory.gate import _correctable_sulfur
from neftecode.domain.production.park import capacity_tonnes
from neftecode.domain.shared.primitives import QUALITIES


def supply_bounds(config, inflow, horizon):
    capacity = capacity_tonnes(config.capacity_m3, config.density_kgm3)
    fill = capacity / inflow
    ready = fill + config.passport_duration_h
    empty = ready + config.nominal_drain_h
    rate = capacity / config.nominal_drain_h
    # Between these boundaries every initial status is constant and the total
    # draining mass is affine, decreasing. Include BOTH sides of every jump by
    # taking the right limit of each preceding interval, never just endpoints.
    boundaries = {0.0, fill, max(0.0, fill - horizon)}
    for index in range(config.tank_count):
        for event in (fill, ready, empty):
            value = event - index * fill
            if 0 < value < fill:
                boundaries.add(value)
    boundaries = sorted(boundaries)
    masses, free = [], []
    for left, right in zip(boundaries, boundaries[1:]):
        middle = (left + right) / 2
        draining = [i for i in range(config.tank_count)
                    if ready <= middle + i * fill < empty]
        masses.append(sum(max(0.0, capacity - rate * (right + i * fill - ready))
                          for i in draining))
        if right > fill - horizon:
            free.append(sum(middle + i * fill >= empty for i in range(config.tank_count)))
    # Reserve more than floating point / empty-tank tolerances in the simulator.
    return {"min_initial_draining_t": max(0.0, min(masses) - config.tank_count * 1e-6),
            "min_available_for_next_fill": min(free) if free else 0,
            "breakpoints_h": boundaries, "fill_duration_h": fill,
            "single_tank_drain_tph": rate}


def certify_phase_interval(scenario, plan, confirmed=(), initial_tanks=None, current_operation=None):
    """Prove phase-dependent Gate conditions for every 0 <= tau < fill time.

    On H < passport time, no freshly filled batch can reach product. All initial
    drainable batches have identical properties. A strictly positive lower bound
    on remaining initial draining stock makes outgoing qualities phase invariant.
    Other stocks, process controls and blend constraints are phase independent
    and remain subject to the ordinary Gate/review/stress checks.
    """
    # use_cases/__init__ also exports MakeDecision, which consumes this service.
    from neftecode.application.use_cases.plan_operation import PlanOperation

    config = scenario.tank_park
    result = {"method": "continuous_interval_bounds", "model_version": "tank-park/1",
              "complete": False, "reasons": [], "bounds": {},
              "horizon_h": scenario.horizon.hours,
              "scope": "Зависимые от фазы условия парка; остальные ограничения проверяет Gate на сетке времени."}
    reasons = result["reasons"]
    if config is None:
        reasons.append("Не описан парк резервуаров")
        return result
    tank = scenario.tank(config.component_tank_id)
    if tank.inflow.value <= 0:
        reasons.append("Для непрерывной проверки нужен положительный приток")
        return result
    bounds = supply_bounds(config, tank.inflow.value, scenario.horizon.hours)
    result["bounds"] = bounds
    fill, hours = bounds["fill_duration_h"], scenario.horizon.hours
    result["tau_domain_h"] = {"lower": 0.0, "upper": fill, "upper_inclusive": False}
    if hours >= min(fill, config.passport_duration_h) - 1e-8:
        reasons.append("Горизонт должен быть короче налива и паспортизации для этого доказательства")
    if (initial_tanks or {}).get(config.component_tank_id) is not None:
        reasons.append("Индивидуальная замена начальной партии не покрыта непрерывной проверкой")
    if 2 * config.tank_count + 3 > 32:
        reasons.append("Не подтверждён предел событий симулятора для такого числа резервуаров")
    planner = PlanOperation(scenario)
    grid = planner.grid()
    demands = [planner._active_step(plan, t).throughput_tph *
               planner._active_step(plan, t).recipe.get(config.component_tank_id, 0.0) for t in grid]
    demand = max(demands)
    bounds["max_demand_tph"] = demand
    bounds["required_initial_draining_t"] = demand * hours
    if demand > bounds["single_tank_drain_tph"]:
        reasons.append("Не подтверждена подача при любой фазе: спрос выше скорости одного слива")
    if bounds["min_initial_draining_t"] <= demand * hours + 1e-6:
        reasons.append("Не подтверждён запас готовых партий на всём интервале фаз")
    # H < fill: at most one filling tank finishes during the horizon. On the
    # phases where it does finish, a tank already AVAILABLE cannot be consumed
    # earlier (the current FILLING tank has priority). It covers the next fill.
    if bounds["min_available_for_next_fill"] < 1:
        reasons.append("Не подтверждён свободный резервуар для следующего налива при любой фазе")
    applied, moves = planner._plan_moves(plan, confirmed, current_operation)
    pending = tuple(applied) + tuple(moves)
    properties = [{name: tank.property_value(name) for name in QUALITIES}]
    properties += [planner.inflow_properties(t, pending).get(config.component_tank_id, {}) for t in grid]
    known = all(isinstance(p.get(name), (int, float)) and math.isfinite(p[name])
                for p in properties for name in QUALITIES)
    if not known or any(p.get("density_kgm3", 0) <= 0 for p in properties if p.get("density_kgm3") is not None):
        reasons.append("Неизвестны свойства начальных партий или входящего потока")
    else:
        sulfur = max(p["sulfur_mgkg"] for p in properties)
        # Mixing is a convex combination. The Gate's best-correctable sulfur is
        # nondecreasing in the batch sulfur, so its upper bound covers all tau.
        corrected = [_correctable_sulfur(sulfur, planner._active_step(plan, t).throughput_tph, scenario)
                     for t in grid]
        limit = scenario.product.limit_value("sulfur_mgkg")
        bounds["batch_sulfur_upper_mgkg"] = sulfur
        bounds["corrected_sulfur_upper_mgkg"] = max(corrected) if all(x is not None for x in corrected) else None
        bounds["sulfur_limit_mgkg"] = limit
        if limit is None or any(x is None or x > limit - 1e-8 for x in corrected):
            reasons.append("Верхняя граница серы партии не проходит проверку корректируемости")
    result["complete"] = not reasons
    return result
