import json
from pathlib import Path

import pytest

from neftecode.composition.decision import make_interactive_demo
from neftecode.evaluation.expert_grid import (AXES, ExpertGrid, GridError, _changes,
                                              _targets, summarise, totals)
from neftecode.infrastructure.config.trust_rules import load_trust_rules

SCENARIOS = Path("config/scenarios")


def raw(name):
    return json.loads((SCENARIOS / f"{name}.json").read_text(encoding="utf-8"))


def grid(name, budget=120):
    trust_cfg, origin = load_trust_rules(Path("."), Path("artifacts"))
    document = raw(name)
    demo = make_interactive_demo(document, budget, trust_cfg, origin)
    return ExpertGrid(demo.run, document, name)


def test_stock_knob_targets_a_tank_that_actually_has_stock():
    document = raw("baseline")
    targets = _targets(document)
    stocked = {t["tank_id"] for t in document["tanks"] if not t.get("on_demand")}
    assert targets["tank_inventory"] in stocked
    assert targets["tank_available"] != targets["tank_inventory"]


def test_grid_without_stocked_tanks_says_so():
    with pytest.raises(GridError):
        _targets({"tanks": [{"tank_id": "reserve", "on_demand": True}]})


def test_grid_covers_every_declared_axis_and_is_reproducible():
    document = raw("baseline")
    first, second = _changes(document), _changes(document)
    assert first == second
    turned = {c["change"] for changes in first for c in changes}
    assert turned == set(AXES)
    assert len(first) == sum(len(v) for v in AXES.values()) + 6


def test_no_combination_gives_a_traceback():
    record = grid("no_feasible").run()
    assert record["tracebacks"] == []
    assert record["combinations"] >= 30


def test_an_inadmissible_limit_is_refused_by_the_loader_not_repaired():
    record = grid("baseline").run()
    weakened = [r for r in record["rows"] if "product_sulfur_mgkg=50.0" in r["changes"]]
    assert weakened and all(r["outcome"] == "rejected_by_loader" for r in weakened)
    assert all("10" in (r["reason"] or "") for r in weakened)


def test_broken_sources_refuse_rather_than_decide():
    record = grid("baseline").run()
    broken = [r for r in record["rows"] if r["fault"] == "both_broken"]
    assert broken and all(r["outcome"] == "refuse" for r in broken)


def test_recomputation_stays_within_what_an_expert_will_wait():
    record = grid("baseline").run()
    assert record["seconds"]["max"] < 10.0


def test_totals_name_the_defects_instead_of_averaging_them_away():
    rows = [{"changes": "x", "fault": "healthy", "outcome": "traceback",
             "error": "KeyError: c0001", "seconds": 0.1, "scenario_id": "s"}]
    report = totals([summarise("s", rows)])
    assert report["tracebacks"] == 1
    assert "НАРУШЕНО" in report["criterion"]
    assert report["traceback_examples"][0]["error"].startswith("KeyError")


def test_totals_confirm_the_criterion_when_clean():
    rows = [{"changes": "x", "fault": "healthy", "outcome": "hold", "error": None,
             "seconds": 0.1, "cost_per_tonne": 1.0, "severity_index": 0.0}]
    report = totals([summarise("s", rows)])
    assert report["tracebacks"] == 0
    assert "НАРУШЕНО" not in report["criterion"]
    assert report["limits"]
