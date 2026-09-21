import json
from pathlib import Path

import pytest

from neftecode.bootstrap import make_demo_service
from neftecode.presentation.web.server import make_handler
from neftecode.application.conditions import ConditionsError, changes_from, defaults_for
from neftecode.presentation.web.query import DemoServerError, parse_conditions
from neftecode.presentation.web.static import StaticError, StaticFiles, resolve_static_dir

ROOT = Path(".")
BUDGET = 250


@pytest.fixture(scope="module")
def service():
    return make_demo_service(ROOT, BUDGET)


def query(**kw):
    return {k: [str(v)] for k, v in kw.items()}



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



def test_unchanged_fields_produce_no_changes(service):
    raw = service.raw("baseline")
    defaults = defaults_for(raw)
    values = query(crude_sulfur_wt_pct=defaults["crude_sulfur_wt_pct"],
                   throughput_tph=defaults["throughput_tph"],
                   tank="reserve", tank_inventory=600.0, tank_available=1)
    assert changes_from(parse_conditions(values), raw) == []


def test_an_edited_field_becomes_a_change(service):
    raw = service.raw("baseline")
    changes = changes_from(parse_conditions(query(crude_sulfur_wt_pct=2.4)), raw)
    assert changes == [{"change": "crude_sulfur_wt_pct", "value": 2.4}]


def test_a_tank_edit_carries_its_target(service):
    raw = service.raw("baseline")
    changes = changes_from(parse_conditions(query(tank="main", tank_inventory=10.0)), raw)
    assert changes == [{"change": "tank_inventory", "value": 10.0, "target": "main"}]


def test_switching_a_tank_off_becomes_a_change(service):
    raw = service.raw("baseline")
    changes = changes_from(parse_conditions(query(tank="reserve", tank_available=0)), raw)
    assert changes == [{"change": "tank_available", "value": False, "target": "reserve"}]


def test_an_empty_field_is_left_alone(service):
    assert changes_from(parse_conditions({"crude_sulfur_wt_pct": [""]}), service.raw("baseline")) == []


def test_a_non_numeric_field_is_refused_by_name(service):
    with pytest.raises(DemoServerError, match="ожидается число"):
        parse_conditions(query(crude_sulfur_wt_pct="много"))



def test_worse_crude_changes_the_decision(service):
    calm = service.decide(query(scenario="baseline", snapshot="synthetic"))
    worse = service.decide(query(scenario="baseline", crude_sulfur_wt_pct=3.2, snapshot="synthetic"))
    assert calm["decision"]["decision_id"] != worse["decision"]["decision_id"]
    assert calm["decision"]["gate"]["checks"] != worse["decision"]["gate"]["checks"]
    assert worse["decision"]["gate"]["feasible"] is True


def test_the_computed_blend_sulfur_follows_the_crude(service):
    def worst(crude):
        result = service.decide(query(scenario="baseline", crude_sulfur_wt_pct=crude, snapshot="synthetic"))
        checks = [c for c in result["decision"]["gate"]["checks"]
                  if c["constraint_id"] == "quality.sulfur_mgkg" and c["observed"] is not None]
        return max(c["observed"] for c in checks)

    assert 0.0 < worst(2.4) - worst(1.35) < 1.0, "ожидается сглаживание запасом 4000 т"


def test_lowering_the_stock_reaches_the_screen(service):
    result = service.decide(query(scenario="baseline", tank="main", tank_inventory=25.0))
    assert result["inventories"]["main"] == 25.0


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



def test_weakening_the_hard_sulfur_limit_is_refused(service):
    result = service.decide(query(scenario="baseline", product_sulfur_mgkg=25))
    assert result["state"] == "error"
    assert "мягче требования ТЗ" in result["message"]


def test_a_negative_stock_is_refused(service):
    result = service.decide(query(scenario="baseline", tank="main", tank_inventory=-5))
    assert result["state"] == "error"


def test_an_unknown_fault_is_refused(service):
    with pytest.raises(ConditionsError, match="Неизвестный отказ"):
        service.decide(query(scenario="baseline", fault="молния"))



def test_the_options_payload_lists_everything_the_panel_offers(service):
    payload = service.options_payload("baseline")
    assert payload["scenario"] == "baseline"
    assert "baseline" in payload["scenarios"]
    assert "healthy" in payload["faults"]
    assert all(set(item) == {"key", "title"} for item in payload["snapshots"])


def test_the_options_payload_is_pure_json_without_markup(service):
    text = json.dumps(service.options_payload("baseline"), ensure_ascii=False, default=str)
    for token in ("<div", "<script", "<style", "<option", "<!doctype"):
        assert token not in text


def test_an_unknown_scenario_in_the_options_falls_back_to_the_first(service):
    assert service.options_payload("выдуманный")["scenario"] in service.scenarios()


def test_the_options_payload_opens_in_the_loading_state(service):
    payload = service.options_payload("baseline")
    assert payload["state"] == "loading"
    assert payload["defaults"]["crude_sulfur_wt_pct"] == 1.35


def test_the_static_directory_defaults_to_the_frontend_build():
    assert resolve_static_dir(Path("/proj")) == Path("/proj/src/frontend/dist")


def test_an_explicit_static_directory_wins(tmp_path):
    assert resolve_static_dir(Path("/proj"), tmp_path) == tmp_path


def test_a_missing_build_is_reported_by_name(tmp_path):
    files = StaticFiles(tmp_path / "нет")
    assert not files.available()
    with pytest.raises(StaticError, match="не найден"):
        files.asset("/")


def test_a_built_frontend_is_served_with_its_own_content_type(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("страница", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("export const a = 1;", encoding="utf-8")
    files = StaticFiles(tmp_path)
    assert files.available()
    assert files.asset("/").content_type.startswith("text/html")
    assert files.asset("/assets/app.js").content_type.startswith("text/javascript")


def test_an_unknown_path_falls_back_to_the_single_page(tmp_path):
    (tmp_path / "index.html").write_text("страница", encoding="utf-8")
    asset = StaticFiles(tmp_path).asset("/какой-то/якорь")
    assert asset.body.decode("utf-8") == "страница"


def test_a_path_outside_the_build_is_refused(tmp_path):
    (tmp_path / "index.html").write_text("страница", encoding="utf-8")
    with pytest.raises(StaticError, match="за пределы"):
        StaticFiles(tmp_path).asset("/../../secrets.txt")


def test_the_handler_factory_builds_a_handler(service):
    handler = make_handler(service)
    assert hasattr(handler, "do_GET")


def test_recomputation_is_reproducible(service):
    values = query(scenario="sour_crude", crude_sulfur_wt_pct=2.0)
    assert service.decide(values)["decision"]["decision_id"] == \
           service.decide(values)["decision"]["decision_id"]
