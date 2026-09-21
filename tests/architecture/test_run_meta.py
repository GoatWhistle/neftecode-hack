from pathlib import Path

from neftecode.bootstrap import make_demo_service

ROOT = Path(".")


def meta(**query):
    values = {"scenario": ["baseline"], **{k: [v] for k, v in query.items()}}
    return make_demo_service(ROOT, 400).recompute(values)["run_meta"]


def test_run_meta_carries_conditions_versions_provider_and_a_stable_fingerprint():
    first = meta(snapshot="20260105-080000")
    again = meta(snapshot="20260105-080000")
    assert first["schema"] == "run-meta/1"
    assert first["conditions_requested"]["scenario"] == "baseline"
    assert first["conditions_applied"]["snapshot"] == "20260105-080000"
    assert first["input_fingerprint"] == again["input_fingerprint"]
    assert len(first["input_fingerprint"]) == 64
    assert "provider" in first["provider"] and "commit" in first["code"] and "dirty" in first["code"]
    assert set(first["input_parts"]) == {"scenario_sha256", "snapshot_sha256", "model"}
    assert first["severity_profile"].startswith("severity-profile/1")


def test_a_changed_condition_changes_the_fingerprint_and_is_listed_as_applied():
    base = meta(snapshot="20260105-080000")
    changed = meta(snapshot="20260105-080000", tank="main", tank_available="0")
    assert changed["input_fingerprint"] != base["input_fingerprint"]
    assert {"change": "tank_available", "value": False, "target": "main"} in changed["conditions_applied"]["changes"]
    assert base["conditions_applied"]["changes"] == []
    other_snapshot = meta(snapshot="20260724-030000")
    assert other_snapshot["input_parts"]["snapshot_sha256"] != base["input_parts"]["snapshot_sha256"]
