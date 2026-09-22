
import json
import hashlib
import subprocess
import sys
from pathlib import Path

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.application.use_cases.replay_decisions import ExecutionState, ReplayDecisions, SIMULATED
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.presentation.cli import COMMANDS
from neftecode.bootstrap import fingerprint, make_demo_service
from neftecode.application.services.robustness import RobustnessCheck
from neftecode.application.services.tank_estimate import default_tank_estimate_factory


ROOT = Path(".")
SCENARIOS = ROOT / "config/scenarios"
EXPECTED = {
    "ample_reserve": ("recommend_scenario", 300.0, "044dda345e8c0f68afb1ccbc6e388374aa77911bc53637004242856b117a8917"),
    "baseline": ("hold", 300.0, "2ae6e42f4a6440c2a15e9e481209b3d1ef7b3efdd74d74260b17a9c33327930d"),
    "no_feasible": ("refuse", None, "f6ed902acb25aaf5b9320ef83319947bf7abb3a8be45760b28f662454d0f5c21"),
    "sour_crude": ("recommend_scenario", 300.0, "fa0899a06a2b4890767df72388694f23e0fc0a0aa3aea7384435aa512276cff3"),
}
DECISION_KEYS = {
    "alternatives", "commercial_release_allowed", "cost_per_tonne", "current_operation", "lookahead",
    "decision_id", "gate", "immediate_action", "note", "production_t", "reason",
    "refusal", "rejected", "robustness", "scenario_id", "scope", "selected_plan",
    "severity_index", "status", "tank_estimate", "trace", "deployment_readiness",
    "selection_policy", "severity", "tradeoff", "consequences",
}
ADDITIVE_KEYS = {"severity", "tradeoff", "consequences"}


def decision(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenario = load_scenario(path)
    return MakeDecision(scenario, robustness_evaluator=RobustnessCheck(
        scenario, raw, scenario_parser=parse_scenario
    ), scenario_parser=parse_scenario, tank_estimate_factory=default_tank_estimate_factory).decide(
        budget=DEFAULT_BUDGET, raw_scenario=raw)


def test_four_scenario_outputs_are_frozen():
    for name, (status, production, digest) in EXPECTED.items():
        result = decision(SCENARIOS / f"{name}.json")
        assert (result["status"], result["production_t"]) == (status, production)
        assert set(result) == DECISION_KEYS
        assert result["commercial_release_allowed"] is False
        assert result["deployment_readiness"]["ready"] is False
        assert {item["id"] for item in result["deployment_readiness"]["required_inputs"]} == \
               {"tank_farm", "deep_treatment_capacity"}
        assert (result["immediate_action"] is None) == (name == "no_feasible")
        frozen = {k: v for k, v in result.items() if k not in ADDITIVE_KEYS}
        encoded = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == digest


def test_http_payload_keeps_the_decision_json_shape():
    payload = make_demo_service(ROOT, 400).decide({"scenario": ["baseline"]})
    assert set(payload["decision"]) == DECISION_KEYS
    assert payload["decision"]["status"] == "hold"


def test_pause_resume_remains_bit_for_bit_reproducible():
    path = SCENARIOS / "sour_crude.json"
    scenario = load_scenario(path)
    document = json.loads(path.read_text(encoding="utf-8"))
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
        cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True,
    )
    expected = ("train", "demo", "advise", "snapshot", "vak", "episodes", "tank-check",
                "benchmark", "screen", "scenes", "serve", "agent-demo", "expert-grid")
    assert set(COMMANDS) == set(expected), "состав команд изменился: обновите контракт осознанно"
    for command in expected:
        assert command in completed.stdout, command


def test_application_has_no_outer_library_dependencies():
    forbidden = ("pandas", "numpy", "catboost", "sklearn", "openpyxl", "http", "pathlib")
    application = Path("src/neftecode/application")
    text = "\n".join(path.read_text(encoding="utf-8") for path in application.rglob("*.py"))
    assert not any(name in text for name in forbidden)


def test_fingerprint_tracks_nested_source_files(tmp_path):
    source = tmp_path / "src/neftecode/domain/production/rule.py"
    source.parent.mkdir(parents=True)
    source.write_text("LIMIT = 10\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("locked\n", encoding="utf-8")

    before = fingerprint(tmp_path, {"seed": 42})
    source.write_text("LIMIT = 11\n", encoding="utf-8")
    after = fingerprint(tmp_path, {"seed": 42})

    assert "src/neftecode/domain/production/rule.py" in before["files"]
    assert before["fingerprint"] != after["fingerprint"]
