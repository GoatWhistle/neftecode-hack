import json
import shutil
from pathlib import Path

import pytest

from neftecode.infrastructure.artifacts.research_summary import (
    FINAL, SELECTION, ResearchSummaryError, build_forecast_summary,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "src/frontend/src/features/evidence-passport/fixtures/research-summary-final-2026.json"


def test_summary_carries_artifact_numbers_without_rounding():
    final = json.loads((ROOT / FINAL).read_text(encoding="utf-8"))
    summary = build_forecast_summary(ROOT)
    assert summary["baseline"]["mae_mgkg"] == final["baseline"]["mae_mgkg"]
    assert summary["winner"]["mae_mgkg"] == final["winner"]["mae_mgkg"]
    assert summary["winner"]["exceed_upper"] == final["winner"]["exceed_upper"]
    assert summary["paired_mae_difference"]["ci95_mgkg"] == final["paired_mae_winner_minus_baseline"]["ci95"]
    assert summary["paired_targets"] == final["paired_available_targets"]
    assert summary["model_link"]["evaluation_fingerprint"] == final["run_policy"]["evaluation_model_fingerprint"]


def test_goal_is_not_met_and_stays_research_target():
    goal = build_forecast_summary(ROOT)["goal"]
    assert goal["max"] == 0.05
    assert goal["kind"] == "research_target"
    assert goal["met_by_winner"] is False
    assert goal["met_by_baseline"] is False


def test_committed_frontend_fixture_matches_builder():
    """Фикстура паспорта получена этим сборщиком, а не переписана вручную."""
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == build_forecast_summary(ROOT)


def _copy(tmp_path: Path) -> Path:
    for rel in (FINAL, SELECTION):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, target)
    return tmp_path


def test_non_finite_metric_is_rejected(tmp_path):
    root = _copy(tmp_path)
    path = root / FINAL
    value = json.loads(path.read_text(encoding="utf-8"))
    value["winner"]["mae_mgkg"] = None
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ResearchSummaryError):
        build_forecast_summary(root)


def test_mismatched_selection_is_rejected(tmp_path):
    root = _copy(tmp_path)
    path = root / SELECTION
    value = json.loads(path.read_text(encoding="utf-8"))
    value["selected"] = "catboost_residual"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ResearchSummaryError):
        build_forecast_summary(root)


@pytest.mark.parametrize("field", ["total_targets", "paired_available_targets"])
def test_fractional_counter_is_rejected_not_truncated(tmp_path, field):
    root = _copy(tmp_path)
    path = root / FINAL
    value = json.loads(path.read_text(encoding="utf-8"))
    value[field] = value[field] + 0.9
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ResearchSummaryError, match="целое"):
        build_forecast_summary(root)
