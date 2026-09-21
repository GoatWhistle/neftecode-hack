import json
from pathlib import Path

import pytest

from neftecode.evaluation.independent import (DEFAULT_INDEPENDENT_ENVIRONMENTS,
                                               apply_environment, run_independent_study)
from neftecode.infrastructure.config.scenario import parse_scenario


def raw(name="sour_crude"):
    return json.loads(Path(f"config/scenarios/{name}.json").read_text(encoding="utf-8"))


def test_hidden_environment_changes_response_delay_and_mixing_without_mutating_optimizer_input():
    original = raw()
    before = json.dumps(original, sort_keys=True)
    hidden = apply_environment(original, DEFAULT_INDEPENDENT_ENVIRONMENTS[-1])
    assert json.dumps(original, sort_keys=True) == before
    assert hidden["stages"]["hydrotreating"] != original["stages"]["hydrotreating"]
    hidden_main = next(t for t in hidden["tanks"] if t["tank_id"] == "main")
    original_main = next(t for t in original["tanks"] if t["tank_id"] == "main")
    assert hidden_main["properties"]["sulfur_mgkg"]["value"] > \
           original_main["properties"]["sulfur_mgkg"]["value"]


def test_independent_study_compares_all_strategies_in_every_fixed_environment():
    report = run_independent_study(raw(), budget=120, scenario_parser=parse_scenario)
    assert report["protocol"] == "fixed_hidden_environment_v1"
    assert [item["environment"] for item in report["environments"]] == \
           [item.name for item in DEFAULT_INDEPENDENT_ENVIRONMENTS]
    for item in report["environments"]:
        strategies = item["benchmark"]["strategies"]
        assert {"hold", "threshold", "advisor"}.issubset(strategies)


def test_committed_independent_summary_matches_the_current_fixed_study():
    committed = json.loads(Path("research/results/independent-evaluation-2026-09-20.json").read_text(
        encoding="utf-8"))
    report = run_independent_study(raw(), budget=committed["budget"], scenario_parser=parse_scenario)
    by_name = {item["environment"]: item for item in report["environments"]}
    for name, expected in committed["environments"].items():
        actual = by_name[name]["benchmark"]["strategies"]
        for strategy in ("hold", "threshold", "advisor"):
            for field, value in expected[strategy].items():
                if isinstance(value, float):
                    assert actual[strategy].get(field) == pytest.approx(value)
                else:
                    assert actual[strategy].get(field) == value
