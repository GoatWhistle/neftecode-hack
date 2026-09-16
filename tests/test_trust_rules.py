"""T83: пороги доверия к источникам одни для демо, HTTP и live; демо больше не игнорирует возраст ЛИМС."""
import json
from pathlib import Path

import pytest

from neftecode.bootstrap import run_demo_decision
from neftecode.infrastructure.config.trust_rules import (ORIGIN_DERIVED, ORIGIN_FALLBACK, RULE_KEYS,
                                                         load_trust_rules, source_rules_artifact,
                                                         write_source_rules)
from neftecode.infrastructure.data.data import frozen_rule
from neftecode.presentation.demo import Demo, healthy_state
from neftecode.services.common import Request
from neftecode.services.decision_service import DecisionService

ROOT = Path(".")
EXPERIMENT = json.loads((ROOT / "config/experiment.json").read_text())
FAKE_RULES = {"lab_max_age_hours": 48.0, "pak_max_age_minutes": 30.0, "pak_period_minutes": 10.0,
              "pak_frozen_readings": 4, "pak_conflict_mgkg": 4.749, "telemetry_max_missing_fraction": 0.0938,
              "source_rules": {"derived_until": "2025-01-01T00:00:00", "method": {}, "observed": {}, "note": "тест"}}


def make_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "experiment.json").write_text(json.dumps(EXPERIMENT), encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    return tmp_path


def stale_lab_state() -> dict:
    return dict(healthy_state(), lab_age_hours=500.0)


def lims(result: dict) -> dict:
    return next(source for source in result["screen"]["sources"] if source["name"] == "ЛИМС")


# --- load_trust_rules ---

def test_without_artifact_falls_back_to_experiment_json(tmp_path):
    cfg, origin = load_trust_rules(make_root(tmp_path), tmp_path / "artifacts")
    assert origin == ORIGIN_FALLBACK
    assert cfg == EXPERIMENT
    # frozen_rule должна работать и на запасном конфиге: там нет pak_frozen_readings/pak_period_minutes.
    readings, period = frozen_rule(cfg)
    assert readings >= 2 and period > 0


def test_valid_artifact_overrides_fallback_and_reports_derived_origin(tmp_path):
    root = make_root(tmp_path)
    write_source_rules(root / "artifacts", FAKE_RULES, {"train_end": "2025-01-01", "source_rule_method": {}}, "abc")
    cfg, origin = load_trust_rules(root, root / "artifacts")
    assert origin == ORIGIN_DERIVED
    assert cfg["pak_frozen_readings"] == 4
    assert cfg["telemetry_max_missing_fraction"] == 0.0938
    assert cfg["source_rules"]["derived_until"] == "2025-01-01T00:00:00"
    assert frozen_rule(cfg) == (4, 10.0)
    # Всё, что не относится к порогам, остаётся из experiment.json.
    assert cfg["train_end"] == EXPERIMENT["train_end"]


def test_broken_artifact_is_an_error_not_a_silent_fallback(tmp_path):
    root = make_root(tmp_path)
    (root / "artifacts" / "source_rules.json").write_text("{не json", encoding="utf-8")
    with pytest.raises(ValueError, match="не читается"):
        load_trust_rules(root, root / "artifacts")
    (root / "artifacts" / "source_rules.json").write_text(json.dumps({"schema_version": "v0", "rules": {}}))
    with pytest.raises(ValueError, match="schema_version"):
        load_trust_rules(root, root / "artifacts")
    (root / "artifacts" / "source_rules.json").write_text(
        json.dumps({"schema_version": "v1", "rules": {"lab_max_age_hours": 48}}))
    with pytest.raises(ValueError, match="нет ключей"):
        load_trust_rules(root, root / "artifacts")


# --- запись C1 при обучении ---

def test_source_rules_artifact_has_the_declared_shape_and_writes_nothing_to_config(tmp_path):
    root = make_root(tmp_path)
    before = sorted(path.name for path in (root / "config").iterdir())
    cfg = {"train_end": "2025-01-01", "source_rule_method": EXPERIMENT["source_rule_method"]}
    path = write_source_rules(root / "artifacts", FAKE_RULES, cfg, "fingerprint-1")
    assert path == root / "artifacts" / "source_rules.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema_version"] == "v1"
    assert written["train_end"] == "2025-01-01"
    assert written["method"] == EXPERIMENT["source_rule_method"]
    assert set(written["rules"]) == set(RULE_KEYS)
    assert written["source_rules"] == FAKE_RULES["source_rules"]
    assert written["model_fingerprint"] == "fingerprint-1"
    assert sorted(path.name for path in (root / "config").iterdir()) == before


def test_source_rules_artifact_refuses_incomplete_rules():
    with pytest.raises(ValueError, match="pak_frozen_readings"):
        source_rules_artifact({"lab_max_age_hours": 48}, {}, None)


# --- демо-путь: возраст ЛИМС проверяется ---

@pytest.fixture(scope="module")
def baseline():
    return json.loads((ROOT / "config/scenarios/baseline.json").read_text())


def test_demo_rejects_500h_old_lab_with_derived_thresholds(baseline):
    cfg = {**EXPERIMENT, **{key: FAKE_RULES[key] for key in RULE_KEYS}}
    result = run_demo_decision(baseline, stale_lab_state(), 200, cfg, trust_origin=ORIGIN_DERIVED)
    source = lims(result)
    assert source["usable"] is False
    assert source["max_age_hours"] == 48
    assert any("старше допустимых 48" in reason for reason in source["reasons"])
    assert result["screen"]["rule_origin"] == ORIGIN_DERIVED


def test_demo_rejects_500h_old_lab_with_fallback_thresholds(baseline, tmp_path):
    # Раньше демо получало пустой конфиг и пропускало ЛИМС возрастом 500 ч как пригодный.
    cfg, origin = load_trust_rules(make_root(tmp_path), tmp_path / "artifacts")
    result = run_demo_decision(baseline, stale_lab_state(), 200, cfg, trust_origin=origin)
    assert lims(result)["usable"] is False
    assert result["screen"]["rule_origin"] == ORIGIN_FALLBACK


def test_demo_runner_requires_trust_config(baseline):
    with pytest.raises(TypeError):
        run_demo_decision(baseline, healthy_state(), 200)
    with pytest.raises(ValueError, match="trust_cfg"):
        run_demo_decision(baseline, healthy_state(), 200, None)


def test_interactive_demo_passes_thresholds_and_origin_to_every_run(baseline, tmp_path):
    cfg, origin = load_trust_rules(make_root(tmp_path), tmp_path / "artifacts")
    demo = Demo(baseline, run_demo_decision, cfg, 200, trust_origin=origin)
    result = demo.run([], "stale_lab")
    assert result["screen"]["rule_origin"] == ORIGIN_FALLBACK
    source = lims(result)
    assert source["usable"] is False
    assert any("старше допустимых 48" in reason for reason in source["reasons"])
    assert demo.reset().trust_cfg == cfg


# --- HTTP: decision service применяет присланный trust_config ---

def request(body: dict) -> Request:
    return Request("POST", "/v1/decisions", {}, body, request_id="t83")


def test_decision_service_applies_trust_config_from_the_body(baseline):
    service = DecisionService()
    result = service.decide(request({"scenario": baseline, "state": stale_lab_state(), "budget": 200,
                                     "trust_config": {"lab_max_age_hours": 48, "pak_max_age_minutes": 30},
                                     "trust_origin": ORIGIN_FALLBACK}))
    source = next(item for item in result["sources"] if item["name"] == "ЛИМС")
    assert source["usable"] is False
    assert any("старше допустимых 48" in reason for reason in source["reasons"])
    assert result["trust_origin"] == ORIGIN_FALLBACK
    # Тот же порог дошёл и до самого решения: агент данных в журнале видит устаревший анализ.
    data_step = next(item for item in result["decision"]["trace"] if item["agent"] == "data")
    assert data_step["primary"] == "ПАК"


def test_decision_service_without_trust_config_keeps_the_old_empty_config(baseline):
    # Обратная совместимость для старых клиентов: без trust_config пороги не заданы и возраст не проверяется.
    # Это допустимо только для них; gateway всегда шлёт trust_config.
    service = DecisionService()
    result = service.decide(request({"scenario": baseline, "state": stale_lab_state(), "budget": 200}))
    source = next(item for item in result["sources"] if item["name"] == "ЛИМС")
    assert source["usable"] is True
    assert result["trust_origin"] is None


def test_decision_service_rejects_a_non_object_trust_config(baseline):
    from neftecode.services.common import ServiceError
    with pytest.raises(ServiceError, match="trust_config"):
        DecisionService().decide(request({"scenario": baseline, "trust_config": [48]}))


# --- live: происхождение порогов в снимке ---

def test_live_snapshot_carries_trust_origin_through_the_wire():
    from neftecode.application.contracts import LiveSnapshot

    snapshot = LiveSnapshot.from_dict({"at": "2026-01-05T08:00:00", "state": {}, "trust": {},
                                       "trust_config": {"lab_max_age_hours": 48},
                                       "trust_origin": "derived:model.pkl"})
    assert snapshot.trust_origin == "derived:model.pkl"
    assert LiveSnapshot.from_dict(snapshot.to_dict()).trust_origin == "derived:model.pkl"
    assert LiveSnapshot.from_dict({"at": "2026-01-05T08:00:00", "state": {}, "trust": {}}).trust_origin is None
    with pytest.raises(ValueError, match="trust_origin"):
        LiveSnapshot.from_dict({"at": "2026-01-05T08:00:00", "state": {}, "trust": {}, "trust_origin": 1})


def test_local_snapshot_provider_uses_the_model_thresholds(monkeypatch):
    from neftecode.infrastructure.live.advisor import LocalSnapshotProvider

    monkeypatch.setattr("neftecode.infrastructure.live.advisor.state_at", lambda *args: stale_lab_state())
    bundle = {"config": {"calibration_end": "2026-01-01", "lab_max_age_hours": 48, "pak_max_age_minutes": 30}}
    snapshot = LocalSnapshotProvider(None, None, None, bundle).snapshot("2026-01-05T08:00:00")
    assert snapshot.trust_origin == "derived:model.pkl"
    assert snapshot.trust_cfg == bundle["config"]
    assert snapshot.trust["sources"]["ЛИМС"]["usable"] is False
