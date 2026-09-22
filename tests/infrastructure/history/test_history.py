from copy import deepcopy
import json
from pathlib import Path

import pytest

from neftecode.application.history.prepare import HistoryError, HistoryRequest, PrepareHistoricalState, run_prepared_history
from neftecode.composition.decision import run_demo_decision
from neftecode.infrastructure.history.source import LocalHistorySource
from neftecode.infrastructure.history.overview import bounded_response

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("at,code", [
    ("2025-12-29T23:59:59", "outside_coverage"),
    ("2026-01-06T00:00:01", "outside_coverage"),
    ("2025-12-31T23:59:59", "model_not_available"),
])
def test_coverage_and_model_boundaries(history, at, code):
    with pytest.raises(HistoryError) as exc:
        PrepareHistoricalState(history[0]).execute(HistoryRequest(at=at))
    assert exc.value.code == code


def test_lims_publication_boundary_and_unrounded_asof(history):
    source, *_ = history
    before, _ = source.prepare_at("2026-01-05T13:59:59")
    exact, _ = source.prepare_at("2026-01-05T14:00:00")
    assert before["state"]["lab_value"] == 8
    assert before["state"]["lab_available_time"] == "2026-01-04T14:00:00"
    assert before["state"]["decision_time"] == "2026-01-05T13:59:59"
    assert before["state"]["measurements"]["ht.T6"]["time"] == "2026-01-05T13:50:00"
    assert exact["state"]["lab_value"] == 999
    assert exact["state"]["lab_available_time"] == "2026-01-05T14:00:00"


def test_future_mutation_does_not_change_state_or_forecast(history):
    source, signals, lab, online, _ = history
    at = "2026-01-05T08:07:00"
    first, _ = source.prepare_at(at)
    signals.loc[signals.index > at] = 9999
    online.loc[online.time > at, "value"] = 7777
    lab.loc[lab.time > at, "value"] = 8888
    second, _ = source.prepare_at(at)
    assert first == second


def test_exclusion_is_a_source_warning_not_a_blanket_decision_ban(history):
    result = PrepareHistoricalState(history[0]).execute(HistoryRequest(at="2026-01-05T01:00:00"))
    assert result["available"] is True
    assert result["exclusions"]["items"][0]["reason"] == "Зависание ПАК"
    assert result["exclusions"]["items"][0]["blocks_decision"] is False


def test_overview_has_no_snapshot_builder_forecast_llm_or_training(history, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Модель/сборка/решение вызваны при просмотре истории")
    monkeypatch.setattr("neftecode.infrastructure.history.source.build_snapshot", forbidden)
    monkeypatch.setattr("neftecode.infrastructure.ml.forecast.predict_candidate", forbidden)
    monkeypatch.setattr("neftecode.infrastructure.ml.forecast.run_experiment", forbidden)
    result = history[0].overview("2026-01-05T08:00:00", "2026-01-05T13:59:59", points=48)
    assert len(result["points"]) == 48
    assert all(row["lab_value"] == 8 for row in result["points"])
    assert all(row["lab_available_time"] <= row["at"] for row in result["points"])
    assert len(json.dumps(result).encode()) < 262144
    for points in [0, 49, True]:
        with pytest.raises(HistoryError, match="48"):
            history[0].overview("2026-01-05T08:00:00", "2026-01-05T13:59:59", points=points)
    with pytest.raises(HistoryError, match="позже"):
        history[0].overview("2026-01-05T13:00:00", "2026-01-05T08:00:00")
    with pytest.raises(HistoryError, match="256"):
        bounded_response({"large": "x" * 262144})


def test_snapshot_only_delivery_is_honest(tmp_path):
    out = tmp_path / "artifacts"
    (out / "snapshots").mkdir(parents=True)
    state = {"decision_time": "2026-01-05T08:00:00", "origin": "real_measurements_at_decision_time"}
    item = {"schema_version": "v1", "at": state["decision_time"], "state": state,
            "trust": {}, "forecast": {}, "measured": {}}
    (out / "snapshots/20260105-080000.json").write_text(json.dumps(item))
    source = LocalHistorySource(tmp_path, out)
    assert source.catalog()["arbitrary"]["available"] is False
    assert len(source.catalog()["items"]) == 1
    assert PrepareHistoricalState(source).execute(HistoryRequest(snapshot="20260105-080000"))["available"] is True
    with pytest.raises(HistoryError) as exc:
        source.prepare_at("2026-01-05T08:07:00")
    assert exc.value.code == "measurements_unavailable"


def test_missing_telemetry_is_not_replaced_by_preset(history):
    source, signals, *_ = history
    signals.loc["2026-01-05T00:00:00":] = float("nan")
    result = PrepareHistoricalState(source).execute(HistoryRequest(at="2026-01-05T08:07:00"))
    assert result["snapshot"]["state"]["measurements"]["ht.T6"] is None
    assert result["trust_usable"] is False
    assert result["effective_at"] == "2026-01-05T08:07:00"


def test_nonpreset_passes_existing_pipeline_and_reproduces_numeric_result(history):
    source = history[0]
    request = HistoryRequest(at="2026-01-05T08:07:00", changes=(
        {"change": "tank_available", "target": "reserve", "value": False},))
    prepared = PrepareHistoricalState(source).execute(request)
    original = deepcopy(prepared)
    raw = json.loads((ROOT / "config/scenarios/baseline.json").read_text())
    first = run_prepared_history(prepared, raw, run_demo_decision, 120, history[4]["config"])
    second = run_prepared_history(prepared, raw, run_demo_decision, 120, history[4]["config"])
    assert first["screen"]["decision_time"] == "2026-01-05T08:07:00"
    assert first["decision"]["decision_id"] == second["decision"]["decision_id"]
    assert first["decision"]["status"] in {"hold", "recommend_scenario", "refuse"}
    assert first["applied"] == list(request.changes)
    assert first["snapshot"] == "20260105-080700"
    assert prepared == original
