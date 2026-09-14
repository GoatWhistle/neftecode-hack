"""Public behavior that must survive the architectural move unchanged."""

import json
import hashlib
import subprocess
import sys
from pathlib import Path

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.replay_decisions import ExecutionState, ReplayDecisions, SIMULATED
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.bootstrap import fingerprint, make_demo_service
from neftecode.evaluation.robustness import RobustnessCheck


ROOT = Path(".")
SCENARIOS = ROOT / "config/scenarios"
EXPECTED = {
    "ample_reserve": ("recommend_scenario", 300.0, "490caadf06fbf50ffbacbf7af509cfa2cbc7d47486b1a5a87d561c9839c59b61"),
    "baseline": ("hold", 300.0, "bbd90febc7a2b34dc8282586dc524e40f9abb9b18c682392ea24a4c5fc341237"),
    "no_feasible": ("refuse", None, "776a837ed0ac98f39595f9c66b205a67efeb0900b5ad783ca927a3465022ad9a"),
    "sour_crude": ("recommend_scenario", 180.0, "d6eca42bd8a26d8f86c0164271398d3d04e1d353da1a0942cf574bce466d238c"),
}
DECISION_KEYS = {
    "alternatives", "commercial_release_allowed", "cost_per_tonne", "current_operation", "lookahead",
    "decision_id", "gate", "immediate_action", "note", "production_t", "reason",
    "refusal", "rejected", "robustness", "scenario_id", "scope", "selected_plan",
    "severity_index", "status", "trace",
}


def decision(path: Path) -> dict:
    raw = json.loads(path.read_text())
    scenario = load_scenario(path)
    return MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, raw, scenario_parser=parse_scenario
    )).decide(
        budget=400, raw_scenario=raw)


def test_four_scenario_outputs_are_frozen():
    for name, (status, production, digest) in EXPECTED.items():
        result = decision(SCENARIOS / f"{name}.json")
        assert (result["status"], result["production_t"]) == (status, production)
        assert set(result) == DECISION_KEYS
        assert result["commercial_release_allowed"] is False
        assert (result["immediate_action"] is None) == (name == "no_feasible")
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == digest


def test_http_payload_keeps_the_decision_json_shape():
    payload = make_demo_service(ROOT, 400).decide({"scenario": ["baseline"]})
    assert set(payload["decision"]) == DECISION_KEYS
    assert payload["decision"]["status"] == "hold"


def test_pause_resume_remains_bit_for_bit_reproducible():
    path = SCENARIOS / "sour_crude.json"
    scenario = load_scenario(path)
    document = json.loads(path.read_text())
    replay = ReplayDecisions(scenario, document, budget=300,
                             robustness_evaluator=RobustnessCheck(
                                 scenario, document, scenario_parser=parse_scenario))
    moments = [
        {"at": "2026-01-05T08:00:00"},
        {"at": "2026-01-05T08:30:00"},
        {"at": "2026-01-05T09:00:00"},
    ]
    whole = replay.run(moments, SIMULATED)
    first = replay.run(moments[:2], SIMULATED)
    restored = ExecutionState.from_dict(json.loads(json.dumps(first["final_execution"])))
    resumed = replay.run(moments[2:], SIMULATED, execution=restored)
    assert resumed["final_execution"] == whole["final_execution"]
    assert resumed["records"][0]["decision"] == whole["records"][2]["decision"]


def test_cli_keeps_all_commands():
    completed = subprocess.run(
        [sys.executable, "-m", "neftecode.presentation.cli", "--help"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    for command in ("train", "demo", "advise", "vak", "episodes", "benchmark", "screen", "scenes", "serve"):
        assert command in completed.stdout


def test_application_has_no_outer_library_dependencies():
    forbidden = ("pandas", "numpy", "catboost", "sklearn", "openpyxl", "http", "pathlib")
    application = Path("src/neftecode/application")
    text = "\n".join(path.read_text() for path in application.rglob("*.py"))
    assert not any(name in text for name in forbidden)


def test_fingerprint_tracks_nested_source_files(tmp_path):
    source = tmp_path / "src/neftecode/domain/production/rule.py"
    source.parent.mkdir(parents=True)
    source.write_text("LIMIT = 10\n")
    (tmp_path / "uv.lock").write_text("locked\n")

    before = fingerprint(tmp_path, {"seed": 42})
    source.write_text("LIMIT = 11\n")
    after = fingerprint(tmp_path, {"seed": 42})

    assert "src/neftecode/domain/production/rule.py" in before["files"]
    assert before["fingerprint"] != after["fingerprint"]
