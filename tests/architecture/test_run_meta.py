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
    assert set(first["input_parts"]) == {"conditions", "scenario_sha256", "snapshot", "snapshot_sha256", "model",
                                         "response_binding", "severity_profile"}
    assert first["input_parts"]["conditions"] == first["conditions_requested"]
    assert first["severity_profile"].startswith("severity-profile/1")


def test_a_changed_condition_changes_the_fingerprint_and_is_listed_as_applied():
    base = meta(snapshot="20260105-080000")
    changed = meta(snapshot="20260105-080000", tank="main", tank_available="0")
    assert changed["input_fingerprint"] != base["input_fingerprint"]
    assert {"change": "tank_available", "value": False, "target": "main"} in changed["conditions_applied"]["changes"]
    assert base["conditions_applied"]["changes"] == []
    other_snapshot = meta(snapshot="20260724-030000")
    assert other_snapshot["input_parts"]["snapshot_sha256"] != base["input_parts"]["snapshot_sha256"]


def _copy_artifacts(tmp_path, snapshots=True):
    import shutil

    out = tmp_path / "out"
    out.mkdir()
    for item in Path("artifacts").iterdir():
        if item.is_file():
            shutil.copy(item, out / item.name)
    if snapshots:
        shutil.copytree(Path("artifacts") / "snapshots", out / "snapshots")
    return out


def test_provenance_reads_the_model_from_the_out_directory(tmp_path):
    import hashlib
    import json
    from neftecode.infrastructure.artifacts.provenance import training_fingerprint

    out = _copy_artifacts(tmp_path, snapshots=False)
    (out / "manifest.json").write_text(json.dumps({"fingerprint": "OUT-ONLY-MANIFEST"}), encoding="utf-8")
    service = make_demo_service(ROOT, 400, out=out)
    model = service.provenance()["model"]
    assert model["training_fingerprint"] == "OUT-ONLY-MANIFEST"
    assert model["response_model_sha256"] == hashlib.sha256((out / "response_model.json").read_bytes()).hexdigest()
    assert training_fingerprint(ROOT / "artifacts") != "OUT-ONLY-MANIFEST"
    standard = make_demo_service(ROOT, 400).provenance()["model"]
    assert standard["response_model_sha256"] == hashlib.sha256(
        (ROOT / "artifacts" / "response_model.json").read_bytes()).hexdigest()


def test_replacing_the_model_file_does_not_relabel_the_loaded_model(tmp_path):
    """Хеш и модель фиксируются вместе при создании сервиса; новый файл действует только после перезапуска."""
    import hashlib
    import json

    out = _copy_artifacts(tmp_path)
    path = out / "response_model.json"
    original = path.read_bytes()
    service = make_demo_service(ROOT, 400, out=out)
    loaded = service.provenance()["model"]
    first = service.recompute({"scenario": ["baseline"], "snapshot": ["20260105-080000"]})
    cached = service.decide({"scenario": ["baseline"], "snapshot": ["20260105-080000"]})

    changed = json.loads(original)
    onset = changed.get("response_onset_hours", 2.0)
    changed["response_onset_hours"] = 3.0 if onset != 3.0 else 2.5
    path.write_text(json.dumps(changed), encoding="utf-8")
    replaced = hashlib.sha256(path.read_bytes()).hexdigest()

    again = service.recompute({"scenario": ["baseline"], "snapshot": ["20260105-080000"]})
    assert service.provenance()["model"] == loaded
    assert loaded["response_model_sha256"] == hashlib.sha256(original).hexdigest() != replaced
    assert again["run_meta"]["model"]["response_model_sha256"] == loaded["response_model_sha256"]
    assert again["binding"]["response_lag_hours"] == first["binding"]["response_lag_hours"]
    assert cached["run_meta"] == first["run_meta"]

    restarted = make_demo_service(ROOT, 400, out=out)
    after = restarted.recompute({"scenario": ["baseline"], "snapshot": ["20260105-080000"]})
    assert restarted.provenance()["model"]["response_model_sha256"] == replaced
    assert after["run_meta"]["model"]["response_model_sha256"] == replaced
    assert after["run_meta"]["input_fingerprint"] != first["run_meta"]["input_fingerprint"]
    assert first["binding"]["response_lag_hours"]["value"] == onset
    assert after["binding"]["response_lag_hours"]["value"] == changed["response_onset_hours"]


def test_code_version_is_captured_at_process_start():
    code = make_demo_service(ROOT, 400).provenance()["code"]
    assert code["captured"] == "process_start" and code["captured_at"]
    assert "commit" in code and "dirty" in code
