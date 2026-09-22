from pathlib import Path
import copy

import pytest

from neftecode.application.conditions import state_under
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.composition.decision import make_demo_service
from neftecode.domain.production.park import capacity_tonnes
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.live.snapshots import bind_snapshot


@pytest.fixture(scope="module")
def historical_normal():
    service = make_demo_service(Path.cwd())
    demo = service.demo_factory(service.raw("baseline"), service.budget)
    snapshot = demo.snapshot("20260105-080000")
    _, raw = bind_snapshot(demo.raw, state_under(snapshot, "healthy"), snapshot,
                           demo.response_model, demo.trust_cfg)
    return raw


@pytest.mark.parametrize("at_end", [False, True])
def test_normal_phase_boundaries_preserve_inflow_and_allow_hold(historical_normal, at_end):
    raw = copy.deepcopy(historical_normal)
    scenario = parse_scenario(raw)
    config = scenario.tank_park
    inflow = scenario.tank(config.component_tank_id).inflow.value
    fill_h = capacity_tonnes(config.capacity_m3, config.density_kgm3) / inflow
    tau = fill_h - .5 if at_end else 0.0
    # Rounded external phases reproduce the former sub-nanohour event loss too.
    raw["tank_park"]["phase_offsets_h"] = [round((tau + i * fill_h) % (4 * fill_h), 9)
                                          for i in range(4)]
    maker = MakeDecision(parse_scenario(raw))
    plans, _ = maker._build_plans(100, None)
    hold = next(plan for plan in plans if plan.plan_id == "hold")
    evaluation = maker._evaluate_plan(hold, (), None, None)
    assert evaluation.feasible, evaluation.gate.rejection_reasons()
    terminal = evaluation.park["terminal"]
    assert terminal["total_in_t"] == pytest.approx(inflow * terminal["elapsed_h"])
    assert terminal["balance_error_t"] == pytest.approx(0.0, abs=1e-6)
    if at_end:
        assert terminal["tanks"][0]["status"] == "awaiting_passport"
    else:
        initial = evaluation.park["frames"][0]["state"]["tanks"][0]
        assert initial["mass_t"] == 0.0
        assert all(value is None for value in initial["properties"].values())
