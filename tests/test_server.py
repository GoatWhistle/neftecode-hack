"""The interactive demonstration server: every change goes through the real core."""
import json
from pathlib import Path

import pytest

from neftecode.server import (DemoService, DemoServerError, changes_from, defaults_for,
                              make_handler)

ROOT = Path(".")
BUDGET = 250


@pytest.fixture(scope="module")
def service():
    return DemoService(ROOT, BUDGET)


def query(**kw):
    return {k: [str(v)] for k, v in kw.items()}


# --- Scenarios and defaults ---

def test_every_shipped_scenario_is_offered(service):
    assert set(service.scenarios()) >= {"baseline", "sour_crude", "no_feasible", "ample_reserve"}


def test_an_unknown_scenario_is_refused(service):
    with pytest.raises(DemoServerError, match="не найден"):
        service.raw("выдуманный")


def test_defaults_describe_what_the_panel_can_change(service):
    defaults = defaults_for(service.raw("baseline"))
    assert defaults["crude_sulfur_wt_pct"] == 1.35
    assert defaults["product_sulfur_mgkg"] == 10.0
    assert defaults["throughput_tph"] == 100.0
    assert {t["id"] for t in defaults["tanks"]} == {"main", "reserve", "light"}


# --- Only real edits become changes ---

def test_unchanged_fields_produce_no_changes(service):
    raw = service.raw("baseline")
    defaults = defaults_for(raw)
    values = query(crude_sulfur_wt_pct=defaults["crude_sulfur_wt_pct"],
                   throughput_tph=defaults["throughput_tph"],
                   tank="reserve", tank_inventory=600.0, tank_available=1)
    assert changes_from(values, raw) == []


def test_an_edited_field_becomes_a_change(service):
    raw = service.raw("baseline")
    changes = changes_from(query(crude_sulfur_wt_pct=2.4), raw)
    assert changes == [{"change": "crude_sulfur_wt_pct", "value": 2.4}]


def test_a_tank_edit_carries_its_target(service):
    raw = service.raw("baseline")
    changes = changes_from(query(tank="reserve", tank_inventory=10.0), raw)
    assert changes == [{"change": "tank_inventory", "value": 10.0, "target": "reserve"}]


def test_switching_a_tank_off_becomes_a_change(service):
    raw = service.raw("baseline")
    changes = changes_from(query(tank="reserve", tank_available=0), raw)
    assert changes == [{"change": "tank_available", "value": False, "target": "reserve"}]


def test_an_empty_field_is_left_alone(service):
    assert changes_from({"crude_sulfur_wt_pct": [""]}, service.raw("baseline")) == []


def test_a_non_numeric_field_is_refused_by_name(service):
    with pytest.raises(DemoServerError, match="ожидается число"):
        changes_from(query(crude_sulfur_wt_pct="много"), service.raw("baseline"))


# --- A change reaches the calculation ---

def test_worse_crude_changes_the_decision(service):
    calm = service.decide(query(scenario="baseline"))
    worse = service.decide(query(scenario="baseline", crude_sulfur_wt_pct=3.2))
    assert calm["decision"]["decision_id"] != worse["decision"]["decision_id"]
    # A large stock can keep quality within the limit despite worse incoming crude.
    assert calm["decision"]["gate"]["checks"] != worse["decision"]["gate"]["checks"]
    assert worse["decision"]["gate"]["feasible"] is True


def test_the_computed_blend_sulfur_follows_the_crude(service):
    def worst(crude):
        result = service.decide(query(scenario="baseline", crude_sulfur_wt_pct=crude))
        checks = [c for c in result["decision"]["gate"]["checks"]
                  if c["constraint_id"] == "quality.sulfur_mgkg" and c["observed"] is not None]
        return max(c["observed"] for c in checks)

    assert 0.0 < worst(2.4) - worst(1.35) < 1.0, "ожидается сглаживание запасом 4000 т"


def test_lowering_the_stock_reaches_the_screen(service):
    result = service.decide(query(scenario="baseline", tank="reserve", tank_inventory=25.0))
    assert result["inventories"]["reserve"] == 25.0


def test_an_injected_fault_is_labelled_and_reaches_the_decision(service):
    result = service.decide(query(scenario="baseline", fault="both_broken"))
    assert result["state"] == "refusal"
    assert result["decision"]["status"] == "refuse"
    assert "не наблюдение из данных" in result["injection"]


def test_a_healthy_state_carries_no_injection_label(service):
    assert service.decide(query(scenario="baseline"))["injection"] is None


def test_the_applied_changes_are_reported_back(service):
    result = service.decide(query(scenario="baseline", crude_sulfur_wt_pct=2.0))
    assert result["applied"] == [{"change": "crude_sulfur_wt_pct", "value": 2.0}]


# --- Inadmissible conditions are refused, not repaired ---

def test_weakening_the_hard_sulfur_limit_is_refused(service):
    result = service.decide(query(scenario="baseline", product_sulfur_mgkg=25))
    assert result["state"] == "error"
    assert "мягче требования ТЗ" in result["message"]


def test_a_negative_stock_is_refused(service):
    result = service.decide(query(scenario="baseline", tank="reserve", tank_inventory=-5))
    assert result["state"] == "error"


def test_an_unknown_fault_is_refused(service):
    with pytest.raises(DemoServerError, match="Неизвестный отказ"):
        service.decide(query(scenario="baseline", fault="молния"))


# --- The page itself ---

def test_the_page_is_self_contained_and_carries_the_payload(service):
    page = service.page("baseline")
    assert page.startswith("<!doctype html>")
    assert "http://" not in page and "https://" not in page
    assert '<script id="payload"' in page


def test_no_placeholder_survives_into_the_page(service):
    page = service.page("baseline")
    for token in ("__STYLE__", "__CONTROLS_STYLE__", "__RENDER_JS__", "__SCENARIOS__",
                  "__FAULTS__", "__PAYLOAD__"):
        assert token not in page


def test_the_page_javascript_has_no_doubled_braces(service):
    """A leftover `{{` from str.format escaping would be a syntax error in the browser."""
    assert "{{" not in service.page("baseline")


def test_the_selected_scenario_is_marked_in_the_list(service):
    assert '<option value="sour_crude" selected>' in service.page("sour_crude")


def test_an_unknown_scenario_in_the_url_falls_back_to_the_first(service):
    assert service.page("выдуманный").startswith("<!doctype html>")


def test_the_page_states_that_nothing_is_prepared_in_advance(service):
    assert "Недопустимое условие отклоняется загрузчиком" in service.page("baseline")


def test_the_handler_factory_builds_a_handler(service):
    handler = make_handler(service)
    assert hasattr(handler, "do_GET")


def test_recomputation_is_reproducible(service):
    values = query(scenario="sour_crude", crude_sulfur_wt_pct=2.0)
    assert service.decide(values)["decision"]["decision_id"] == \
           service.decide(values)["decision"]["decision_id"]
