import pytest

from neftecode.domain.production.park import (
    AVAILABLE,
    AWAITING_PASSPORT,
    DRAINING,
    FILLING,
    READY,
    ParkState,
    ParkTankState,
    capacity_tonnes,
)
from neftecode.domain.production.park_evaluator import ParkEvaluator, ParkStep, TankOperation, initial_park
from neftecode.infrastructure.config.scenario import load_scenario
from neftecode.domain.shared.primitives import ContractError, QUALITIES


PROPERTIES = {
    "sulfur_mgkg": 7.0,
    "t95_c": 340.0,
    "cetane_number": 52.0,
    "density_kgm3": 836.3,
}


def empty(tank_id="main-1", capacity=capacity_tonnes(5000.0, 836.3)):
    return ParkTankState(tank_id, capacity, 0.0, {name: None for name in QUALITIES})


def full_ready():
    tank = empty().start_filling("batch-1")
    return tank.fill(tank.capacity_t, PROPERTIES).advance(12.0)


def test_given_volume_is_converted_once_and_nominal_drain_is_per_tank():
    tank = empty()
    assert tank.capacity_t == pytest.approx(4181.5)
    assert tank.nominal_drain_tph == pytest.approx(4181.5 / 24.0)


def test_full_batch_passport_changes_state_exactly_at_twelve_hours():
    tank = empty().start_filling("batch-1")
    assert tank.status == FILLING
    tank = tank.fill(tank.capacity_t, PROPERTIES)
    assert tank.status == AWAITING_PASSPORT
    assert tank.advance(12.0 - 1e-6).status == AWAITING_PASSPORT
    ready = tank.advance(12.0)
    assert ready.status == READY
    assert ready.passport_ready_in_h == 0.0
    assert ready.properties == PROPERTIES


def test_partial_batch_must_be_closed_and_passported_before_drain():
    tank = empty().start_filling("batch-partial").fill(1000.0, PROPERTIES, hours=4.0)
    with pytest.raises(ContractError, match="готовой паспортизованной"):
        tank.start_draining()
    tank = tank.finish_filling().advance(12.0).start_draining()
    assert tank.status == DRAINING


def test_full_batch_empties_at_24_hours_only_at_nominal_demand():
    draining = full_ready().start_draining()
    before, drawn = draining.drain(draining.nominal_drain_tph, 24.0 - 1e-6)
    assert before.status == DRAINING
    assert before.mass_t > 0
    after, tail = before.drain(draining.nominal_drain_tph, 1e-6)
    assert after.status == AVAILABLE and after.mass_t == 0.0 and after.batch_id is None
    assert drawn + tail == pytest.approx(draining.capacity_t)


def test_low_variable_demand_extends_drain_and_never_exceeds_nominal_rate():
    draining = full_ready().start_draining()
    after, drawn = draining.drain(50.0, 24.0)
    assert drawn == pytest.approx(1200.0)
    assert after.status == DRAINING
    assert after.mass_t == pytest.approx(draining.capacity_t - 1200.0)
    capped, capped_drawn = draining.drain(10_000.0, 1.0)
    assert capped_drawn == pytest.approx(draining.nominal_drain_tph)
    assert capped.status == DRAINING


def test_inflow_only_during_filling_and_overflow_is_rejected():
    tank = empty()
    with pytest.raises(ContractError, match="только при filling"):
        tank.fill(1.0, PROPERTIES)
    filling = tank.start_filling("batch-1")
    with pytest.raises(ContractError, match="переполняет"):
        filling.fill(filling.capacity_t + 0.1, PROPERTIES)


def test_unknown_quality_propagates_instead_of_becoming_a_number():
    tank = empty().start_filling("batch-1").fill(100.0, PROPERTIES)
    unknown = dict(PROPERTIES, sulfur_mgkg=None)
    mixed = tank.fill(100.0, unknown)
    assert mixed.properties["sulfur_mgkg"] is None
    assert mixed.properties["density_kgm3"] == pytest.approx(836.3)


def test_park_checks_mass_balance_after_every_replacement():
    tank = empty()
    park = ParkState((tank,))
    filling = tank.start_filling("batch-1").fill(100.0, PROPERTIES)
    park = park.replace_tank(filling, inflow_t=100.0)
    draining = filling.finish_filling().advance(12.0).start_draining()
    park = park.replace_tank(draining)
    drained, drawn = draining.drain(20.0, 2.0)
    park = park.replace_tank(drained, outflow_t=drawn)
    assert park.mass_t == pytest.approx(60.0)
    assert park.to_dict()["balance_error_t"] == pytest.approx(0.0)
    with pytest.raises(ContractError, match="массовый баланс"):
        park.replace_tank(drained, outflow_t=1.0)


def test_one_evaluator_runs_multiple_tanks_and_preserves_balance():
    ready = full_ready()
    filling = empty("main-2").start_filling("batch-2")
    park = ParkState((ready, filling))
    result = ParkEvaluator().evaluate(park, [
        ParkStep(1.0, {
            "main-1": TankOperation(start_draining=True, demand_tph=100.0),
            "main-2": TankOperation(inflow_tph=80.0, inflow_properties=PROPERTIES),
        }),
        ParkStep(1.0, {
            "main-1": TankOperation(demand_tph=120.0),
            "main-2": TankOperation(inflow_tph=80.0, inflow_properties=PROPERTIES),
        }),
    ])
    assert result.feasible
    assert result.terminal.total_in_t == pytest.approx(160.0)
    assert result.terminal.total_out_t == pytest.approx(220.0)
    assert result.terminal.to_dict()["balance_error_t"] == pytest.approx(0.0)
    assert result.terminal.tank("main-1").status == DRAINING
    assert result.terminal.tank("main-2").mass_t == pytest.approx(160.0)


def test_evaluator_reports_forbidden_shipping_before_passport():
    waiting = empty().start_filling("batch-1").fill(1000.0, PROPERTIES).finish_filling()
    result = ParkEvaluator().evaluate(ParkState((waiting,)), [
        ParkStep(1.0, {"main-1": TankOperation(start_draining=True, demand_tph=10.0)})
    ])
    assert not result.feasible
    assert "готовой паспортизованной" in result.reasons[0]
    assert result.terminal.total_out_t == 0.0
    assert result.terminal.tank("main-1").status == AWAITING_PASSPORT


def test_evaluator_does_not_redirect_overflow_to_another_tank():
    almost_full = empty().start_filling("batch-1").fill(4180.0, PROPERTIES)
    spare = empty("main-2")
    result = ParkEvaluator().evaluate(ParkState((almost_full, spare)), [
        ParkStep(1.0, {"main-1": TankOperation(inflow_tph=10.0, inflow_properties=PROPERTIES)})
    ])
    assert not result.feasible
    assert "переполняет" in result.reasons[0]
    assert result.terminal.tank("main-1").mass_t == pytest.approx(4180.0)
    assert result.terminal.tank("main-2").mass_t == 0.0


def test_scenario_phase_offsets_create_four_consistent_initial_states():
    scenario = load_scenario("config/scenarios/baseline.json")
    park = initial_park(scenario.tank_park, PROPERTIES, scenario.tank("main").inflow.value)
    assert len(park.tanks) == 4
    assert {tank.status for tank in park.tanks} == {AVAILABLE, FILLING, AWAITING_PASSPORT, DRAINING}
    assert sum(tank.status == DRAINING for tank in park.tanks) == 1
    assert park.to_dict()["balance_error_t"] == pytest.approx(0.0)
