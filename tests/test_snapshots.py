"""Замороженные реальные срезы: демонстрация без task/ идёт через тот же связыватель, что и advise."""
import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.bootstrap import run_demo_decision
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.snapshots import load_snapshots, write_snapshot
from neftecode.presentation.demo import (Demo, DemoError, apply_source_failure, scenes, snapshot_key,
                                         state_origin_label)
from neftecode.presentation.web.server import DemoService

ROOT = Path(".")
BASELINE = json.loads((ROOT / "config/scenarios/baseline.json").read_text())


def real_state(decision_time="2026-01-05T08:00:00", hourly=5.0, t6=367.8):
    when = pd.Timestamp(decision_time)
    return {"decision_time": decision_time, "origin": "real_measurements_at_decision_time",
            "lab_value": 6.8, "lab_age_hours": 14.0, "lab_usable": True,
            "pak_value": 5.88, "pak_age_minutes": 0.0, "pak_usable": True, "pak_frozen": False,
            "pak_conflict": False, "telemetry_missing_fraction": 0.0,
            "pak_last_trusted_value": 5.88, "pak_last_trusted_time": decision_time,
            "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
            "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(), hourly, 6]
                                   for h in range(72)],
            "lab_recent": [],
            "measurements": {"ht.T6": None if t6 is None else {"value": t6, "time": decision_time, "age_min": 0.0},
                             "ht.F9": {"value": 206.1, "time": decision_time, "age_min": 0.0},
                             "ht.F26": {"value": 244.1, "time": decision_time, "age_min": 0.0}}}


def snapshot(label="норма", fingerprint="fp", synthetic=()):
    state = real_state(t6=None if "ht.T6" in synthetic else 367.8)
    edits = [f"{tag}: затёрто" for tag in synthetic]
    if edits:
        state["synthetic_edits"] = edits
    return {"schema_version": "v1", "at": "2026-01-05T08:00:00", "label": label, "why": "тест",
            "state": state, "trust": {"usable": True, "primary": "ЛИМС", "fallback": False},
            "forecast": {"model": "last_pak", "value": 5.88, "lower": 3.68, "upper": 9.13, "available": True,
                         "reason": "тест", "coverage_target": 0.9, "coverage_test_2026": 0.867},
            "measured": state["measurements"], "synthetic_edits": edits,
            "model_fingerprint": fingerprint, "source_rules_fingerprint": None}


@pytest.fixture
def out(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"fingerprint": "fp"}))
    return tmp_path


def trust_cfg():
    return load_trust_rules(ROOT, ROOT / "nowhere")[0]


# --- загрузка ---

def test_snapshots_are_loaded_in_time_order_and_checked_against_the_model(out):
    write_snapshot(out, snapshot())
    later = dict(snapshot(label="позже"), at="2026-02-01T00:00:00")
    write_snapshot(out, later)
    items = load_snapshots(out)
    assert [item["label"] for item in items] == ["норма", "позже"]
    assert load_snapshots(out / "empty") == []


def test_a_snapshot_from_another_model_is_refused(out):
    write_snapshot(out, snapshot(fingerprint="other"))
    with pytest.raises(ValueError, match="другой модели"):
        load_snapshots(out)


def test_a_synthetic_edit_gets_its_own_file_name_and_label(out):
    path = write_snapshot(out, snapshot(synthetic=("ht.T6",)))
    assert path.name.endswith("-synthetic.json")
    item = load_snapshots(out)[0]
    assert snapshot_key(item).endswith("-synthetic")
    assert "затёрта искусственно" in state_origin_label(item["state"], item)


# --- демонстрация на срезе ---

def test_the_demo_binds_the_snapshot_through_the_live_binder():
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 120, snapshots=[snapshot()])
    result = demo.run(snapshot="норма")
    assert result["state_origin"] == "real_measurements_at_decision_time"
    assert result["screen"]["state_origin"].startswith("реальный срез: норма · 05.01.2026 08:00")
    binding = result["binding"]
    assert binding["controls"]["ht_reactor_inlet_temp_c"]["current"]["source"] == "measured"
    assert binding["tank_inflow"]["source"] == "derived"
    sulfur = [c for c in result["decision"]["gate"]["checks"] if c["constraint_id"] == "quality.sulfur_mgkg"]
    # Смесь считается от серы резервуара (среднее ПАК 5.0), а не от сценарных 8.0.
    assert sulfur[0]["observed"] == pytest.approx(0.9 * 5.0 + 0.1 * 2.0)


def test_without_a_snapshot_the_demo_stays_synthetic_and_says_so():
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 120)
    result = demo.run()
    assert result["snapshot"] is None and result["binding"] is None
    assert result["screen"]["state_origin"].startswith("синтетическое состояние")
    with pytest.raises(DemoError, match="не найден"):
        demo.run(snapshot="20990101-000000")


def test_an_injected_fault_on_a_real_snapshot_keeps_the_real_origin():
    state = apply_source_failure(real_state(), "frozen_pak")
    assert state["origin"] == "real_measurements_at_decision_time"
    assert state["injected_fault"] == "frozen_pak" and "инъекция" in state["injection"]
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 120, snapshots=[snapshot()])
    result = demo.run(fault="both_broken", snapshot="норма")
    assert result["decision"]["status"] == "refuse"
    assert "инъекция" in result["screen"]["state_origin"]


def test_scenes_use_real_moments_when_they_exist_and_keep_the_crude_scene_synthetic():
    items = [snapshot("норма"), dict(snapshot("отказ по данных"), at="2026-04-16T10:10:00")]
    plan = {scene["name"]: scene for scene in scenes(BASELINE, items)}
    assert plan["Нормальный режим"]["snapshot"] == "норма"
    assert plan["Ухудшение сырья"]["snapshot"] is None
    assert plan["Зависший поточный анализатор"]["fault"] == "frozen_pak", "среза нет — инъекция"
    without = {scene["name"]: scene for scene in scenes(BASELINE, [])}
    assert all(scene["snapshot"] is None for scene in without.values())


# --- serve ---

def test_the_server_offers_snapshots_first_and_the_synthetic_state_last(out):
    write_snapshot(out, snapshot())
    items = load_snapshots(out)
    service = DemoService(ROOT, lambda raw, budget: Demo(raw, run_demo_decision, trust_cfg(), budget,
                                                         snapshots=items), 120, snapshots=items)
    keys = [key for key, _ in service.snapshot_options()]
    assert keys == ["20260105-080000", "synthetic"]
    page = service.page("baseline")
    assert "синтетическое состояние сценария" in page and "норма · 05.01.2026 08:00" in page
    payload = service.decide({"scenario": ["baseline"]})
    assert payload["snapshot"] == "20260105-080000"
    assert service.decide({"scenario": ["baseline"], "snapshot": ["synthetic"]})["snapshot"] is None
