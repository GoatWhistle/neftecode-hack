"""The offline agent demonstration is deterministic, labelled as scripted and wired into the CLI."""
import json
from argparse import Namespace
from pathlib import Path

from neftecode.composition.commands.agentic import agent_demo
from neftecode.presentation.reports.agent_trace import render_agent_trace

from _agentic_support import legacy_decide


def run(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    agent_demo(Namespace(scenario=None), None, Path.cwd(), tmp_path)
    return json.loads((tmp_path / "agent-demo.json").read_text()), (tmp_path / "agent-demo.md").read_text()


def strip_latency(value):
    if isinstance(value, dict):
        return {k: strip_latency(v) for k, v in value.items() if k != "latency_ms"}
    if isinstance(value, list):
        return [strip_latency(v) for v in value]
    return value


def test_demo_is_deterministic_and_labelled(tmp_path):
    first, text = run(tmp_path / "a")
    second, _ = run(tmp_path / "b")
    assert strip_latency(first) == strip_latency(second)
    assert "не языковая модель" in first["label"] and "provider=scripted" in text
    rows = {r["scenario"]: r for r in first["scenarios"]}
    assert rows["baseline"]["agentic"]["outcome"] == "confirmed_legacy"
    assert rows["sour_crude"]["agentic"]["outcome"] == "selected"
    assert rows["no_feasible"]["agentic"]["status"] == "refuse"
    assert all(r["agentic"]["provider"] == "scripted" for r in first["scenarios"])
    assert rows["sour_crude"]["rendered"] != rows["baseline"]["rendered"]


def test_rendering_is_empty_for_deterministic_decisions():
    assert render_agent_trace(legacy_decide("baseline")) == []
