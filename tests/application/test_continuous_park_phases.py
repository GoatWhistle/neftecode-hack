import copy
import json
import math
import random
from dataclasses import replace
from pathlib import Path

import pytest

from neftecode.application.use_cases.plan_operation import PlanOperation
from neftecode.application.services.park_phase_bounds import certify_phase_interval, supply_bounds
from neftecode.application.services.tank_estimate import default_tank_estimate_factory
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.advisory.optimizer import rank
from neftecode.domain.production.park import DRAINING, capacity_tonnes
from neftecode.domain.production.park_evaluator import initial_park
from neftecode.infrastructure.config.scenario import parse_scenario


def _raw(*, passport=12.0, drain=24.0, inflow=212.6, sulfur=8.0):
    raw = json.loads(Path("config/scenarios/baseline.json").read_text())
    raw["measurement_binding"] = {}
    raw["tank_park"]["passport_duration_h"] = passport
    raw["tank_park"]["nominal_drain_h"] = drain
    raw["tanks"][0]["inflow"]["value"] = inflow
    raw["tanks"][0]["properties"]["sulfur_mgkg"]["value"] = sulfur
    return raw


def _hold(scenario):
    plans, _ = PlanOperation(scenario).build_plans(100)
    return next(plan for plan in plans if plan.plan_id == "hold")


def _phase_raw(raw, tau):
    scenario = parse_scenario(raw)
    config = scenario.tank_park
    fill = capacity_tonnes(config.capacity_m3, config.density_kgm3) / scenario.tank(
        config.component_tank_id
    ).inflow.value
    phased = copy.deepcopy(raw)
    phased["tank_park"]["phase_offsets_h"] = [
        tau + index * fill for index in range(config.tank_count)
    ]
    return phased


def _initial_draining_mass(scenario, tau):
    config = scenario.tank_park
    tank = scenario.tank(config.component_tank_id)
    fill = capacity_tonnes(config.capacity_m3, config.density_kgm3) / tank.inflow.value
    phased = replace(
        config,
        phase_offsets_h=tuple(tau + index * fill for index in range(config.tank_count)),
    )
    properties = {name: tank.property_value(name) for name in tank.properties}
    state = initial_park(phased, properties, tank.inflow.value)
    return sum(item.mass_t for item in state.tanks if item.status == DRAINING)


def test_three_control_phases_can_pass_while_a_fourth_phase_has_no_supply():
    raw = _raw(passport=7.0, drain=15.0, inflow=200.0, sulfur=3.0)
    scenario = parse_scenario(raw)
    config = scenario.tank_park
    fill = capacity_tonnes(config.capacity_m3, config.density_kgm3) / 200.0

    old_phases = (0.0, fill / 2.0, fill - 0.5)
    for tau in old_phases:
        phased = parse_scenario(_phase_raw(raw, tau))
        evaluation = PlanOperation(phased).evaluate(_hold(phased))
        assert evaluation.feasible, (tau, evaluation.gate.rejection_reasons())

    missing_phase = parse_scenario(_phase_raw(raw, 3.0))
    evaluation = PlanOperation(missing_phase).evaluate(_hold(missing_phase))
    assert not evaluation.feasible
    assert any("готовые партии не покрывают спрос" in reason
               for reason in evaluation.park["reasons"])

    certificate = certify_phase_interval(scenario, _hold(scenario))
    assert not certificate["complete"]
    assert certificate["bounds"]["min_initial_draining_t"] == pytest.approx(0.0)
    assert any("запас готовых партий" in reason for reason in certificate["reasons"])


def test_release_refuses_three_phase_winner_without_continuous_coverage():
    raw = _raw(passport=7.0, drain=15.0, inflow=200.0, sulfur=3.0)
    raw["measurement_binding"] = {"tags": {}}
    scenario = parse_scenario(raw)
    maker = MakeDecision(
        scenario,
        scenario_parser=parse_scenario,
        tank_estimate_factory=default_tank_estimate_factory,
    )
    plan = _hold(scenario)
    evaluation = maker._evaluate_plan(plan, (), None, None)
    selected = rank([evaluation], hold_id="hold")

    decision = maker.release(
        selected,
        plan,
        [evaluation],
        {plan.plan_id: plan},
        [],
        raw_scenario=raw,
        budget=100,
    )

    assert decision["status"] == "refuse"
    assert decision["tank_estimate"]["same"] == 3
    assert decision["tank_estimate"]["coverage"]["complete"] is False
    assert decision["selected_plan"] is None


def test_supply_lower_bound_is_below_dense_and_random_phase_samples():
    raw = _raw()
    scenario = parse_scenario(raw)
    config = scenario.tank_park
    inflow = scenario.tank(config.component_tank_id).inflow.value
    bounds = supply_bounds(config, inflow, scenario.horizon.hours)
    fill = bounds["fill_duration_h"]
    samples = [fill * index / 4000.0 for index in range(4001)]
    rng = random.Random(20260922)
    samples += [rng.uniform(0.0, fill) for _ in range(1000)]
    observed = min(_initial_draining_mass(scenario, tau) for tau in samples)

    assert observed + 1e-3 >= bounds["min_initial_draining_t"]
    assert bounds["breakpoints_h"] == sorted(bounds["breakpoints_h"])
    assert bounds["breakpoints_h"][0] == 0.0
    assert bounds["breakpoints_h"][-1] == pytest.approx(fill)


@pytest.mark.parametrize(
    "tank_count, passport, drain, inflow, horizon",
    [
        (2, 5.0, 9.0, 180.0, 3.0),
        (3, 8.0, 17.0, 230.0, 3.0),
        (4, 12.0, 24.0, 212.6, 3.0),
        (5, 4.0, 11.0, 260.0, 2.0),
    ],
)
def test_supply_bounds_hold_on_both_sides_of_every_breakpoint(
    tank_count, passport, drain, inflow, horizon
):
    raw = _raw(passport=passport, drain=drain, inflow=inflow)
    raw["tank_park"]["tank_count"] = tank_count
    raw["tank_park"]["phase_offsets_h"] = [10.0 + 20.0 * index for index in range(tank_count)]
    scenario = parse_scenario(raw)
    config = scenario.tank_park
    bounds = supply_bounds(config, inflow, horizon)
    fill = bounds["fill_duration_h"]
    points = []
    for breakpoint in bounds["breakpoints_h"]:
        if breakpoint == 0.0:
            points.extend((0.0, math.nextafter(0.0, fill)))
        elif math.isclose(breakpoint, fill, rel_tol=0.0, abs_tol=1e-12):
            points.append(math.nextafter(fill, 0.0))
        else:
            points.extend(
                (
                    math.nextafter(breakpoint, 0.0),
                    breakpoint,
                    math.nextafter(breakpoint, fill),
                )
            )

    for tau in points:
        assert 0.0 <= tau < fill
        mass = _initial_draining_mass(scenario, tau)
        assert mass + 1e-3 >= bounds["min_initial_draining_t"], (tau, mass, bounds)
        if tau > fill - horizon + 1e-9:
            # The domain is open at fill.  At the immediate floating-point
            # predecessor, tau + (N - 1) * fill can round to cycle_h and the
            # model's modulo maps that value to phase zero. Probe a few ulps
            # further inside to represent the mathematical left limit.
            availability_tau = tau
            cycle = max(tank_count * fill, fill + passport + drain)
            for _ in range(4):
                if availability_tau + (tank_count - 1) * fill < cycle:
                    break
                availability_tau = math.nextafter(availability_tau, 0.0)
            config_at_tau = replace(
                config,
                phase_offsets_h=tuple(
                    availability_tau + index * fill for index in range(tank_count)
                ),
            )
            tank = scenario.tank(config.component_tank_id)
            properties = {name: tank.property_value(name) for name in tank.properties}
            state = initial_park(config_at_tau, properties, inflow)
            available = sum(item.status == "available" for item in state.tanks)
            assert available >= bounds["min_available_for_next_fill"], (
                tau,
                available,
                bounds,
            )


def test_nominal_fifty_tonne_plan_has_a_complete_continuous_certificate():
    scenario = parse_scenario(_raw())
    plans, _ = PlanOperation(scenario).build_plans(100)
    plan = next(plan for plan in plans if plan.immediate().throughput_tph == 50.0)

    certificate = certify_phase_interval(scenario, plan)

    assert certificate["complete"]
    assert certificate["reasons"] == []
    assert certificate["bounds"]["required_initial_draining_t"] == pytest.approx(150.0)


def test_certified_fifty_tonne_plan_matches_simulation_across_dense_phases():
    raw = _raw()
    scenario = parse_scenario(raw)
    plan = next(
        plan for plan in PlanOperation(scenario).build_plans(100)[0]
        if plan.immediate().throughput_tph == 50.0
    )
    certificate = certify_phase_interval(scenario, plan)
    assert certificate["complete"]
    fill = certificate["bounds"]["fill_duration_h"]
    taus = [fill * index / 200.0 for index in range(200)]
    for breakpoint in certificate["bounds"]["breakpoints_h"]:
        if 0.0 < breakpoint < fill:
            taus.extend((math.nextafter(breakpoint, 0.0), math.nextafter(breakpoint, fill)))

    for tau in taus:
        phased = parse_scenario(_phase_raw(raw, tau))
        evaluation = PlanOperation(phased).evaluate(plan)
        assert evaluation.feasible, (tau, evaluation.gate.rejection_reasons())


def test_legacy_initial_tank_override_is_outside_the_certificate():
    scenario = parse_scenario(_raw())

    certificate = certify_phase_interval(scenario, _hold(scenario), initial_tanks={"main": object()})

    assert not certificate["complete"]
    assert any("legacy" in reason or "начальной партии" in reason
               for reason in certificate["reasons"])


def test_horizon_reaching_passport_time_is_outside_the_certificate():
    base = parse_scenario(_raw())
    long_horizon = replace(base, horizon=replace(base.horizon, hours=13.0))

    certificate = certify_phase_interval(long_horizon, _hold(long_horizon))

    assert not certificate["complete"]
    assert any("короче налива и паспортизации" in reason
               for reason in certificate["reasons"])
