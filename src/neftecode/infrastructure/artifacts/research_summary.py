"""Версионированная сводка уже выполненного исследования прогноза серы для паспорта доказательств.

Модуль ничего не пересчитывает и не обучает: он читает замороженные артефакты
`research/forecast/final-2026.json` и `selection.json`, переносит их числа без округления и
добавляет хеши исходных файлов. Описательные тексты — ссылки на протокол, а не новые утверждения.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "neftecode.research-summary/1"
FINAL = "research/forecast/final-2026.json"
SELECTION = "research/forecast/selection.json"
PROTOCOL = "research/forecast/protocol.md"
EVIDENCE_DOC = "docs/forecast-evidence.md"
# Порог цели записан в протоколе как правило отбора (`mean_exceed_upper_above_0.05`) и §5:
# «exceed_upper — не более 5% в среднем по пяти складкам». Это исследовательская цель, не требование ТЗ.
GOAL_RULE = "mean_exceed_upper_above_"

METRICS = ("mae_mgkg", "rmse_mgkg", "exceed_upper", "two_sided_coverage", "mean_upper_margin_mgkg",
           "mean_interval_width_mgkg", "point_exceedance_recall")


class ResearchSummaryError(ValueError):
    pass


def _read(root: Path, rel: str) -> tuple[dict, str]:
    raw = (root / rel).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ResearchSummaryError(f"{rel}: ожидался объект")
    return value, hashlib.sha256(raw).hexdigest()


def _finite(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ResearchSummaryError(f"{where}: ожидалось конечное число, получено {value!r}")
    return value


def _count(value, where: str) -> int:
    """Счётчик обязан быть целым неотрицательным: дробь не усекается молча."""
    number = _finite(value, where)
    if number < 0 or number != int(number):
        raise ResearchSummaryError(f"{where}: ожидалось целое неотрицательное число, получено {value!r}")
    return int(number)


def _method(block: dict, where: str) -> dict:
    if not isinstance(block, dict) or not isinstance(block.get("method"), str):
        raise ResearchSummaryError(f"{where}: нет метода")
    return {"method": block["method"], **{key: _finite(block.get(key), f"{where}.{key}") for key in METRICS}}


def _goal(selection: dict) -> float:
    rules = [rule for reasons in (selection.get("rejected_candidates") or {}).values() for rule in reasons
             if isinstance(rule, str) and rule.startswith(GOAL_RULE)]
    values = {float(rule[len(GOAL_RULE):]) for rule in rules}
    if len(values) != 1:
        raise ResearchSummaryError(f"{SELECTION}: порог цели exceed_upper не найден однозначно")
    return values.pop()


def build_forecast_summary(root: str | Path) -> dict:
    base = Path(root)
    final, final_sha = _read(base, FINAL)
    selection, selection_sha = _read(base, SELECTION)
    policy = final.get("run_policy") or {}
    if policy.get("selection_evidence_sha256") != selection.get("evidence_sha256"):
        raise ResearchSummaryError("final-2026 и selection.json ссылаются на разные доказательства отбора")
    winner = _method(final.get("winner"), "winner")
    if winner["method"] != selection.get("selected"):
        raise ResearchSummaryError("победитель финального прогона не совпадает с замороженным выбором")
    diff = final.get("paired_mae_winner_minus_baseline") or {}
    ci = diff.get("ci95")
    if not isinstance(ci, list) or len(ci) != 2:
        raise ResearchSummaryError("paired_mae_winner_minus_baseline.ci95: ожидалась пара чисел")
    goal = _goal(selection)
    return {
        "schema": SCHEMA,
        "study_id": "forecast-final-2026",
        "kind": "research_result",
        "sources": [
            {"path": FINAL, "sha256": final_sha, "schema_version": final.get("schema_version")},
            {"path": SELECTION, "sha256": selection_sha, "schema_version": selection.get("schema_version")},
        ],
        "protocol": PROTOCOL,
        "document": EVIDENCE_DOC,
        "subject": {
            "quantity": "sulfur_mgkg",
            "object": "stream_after_hydrotreating",
            "target": "next_lims_sample",
            "unit": "мг/кг",
            "reference": f"{PROTOCOL} §1",
        },
        "period": str(final.get("period")),
        "total_targets": _count(final.get("total_targets"), "total_targets"),
        "paired_targets": _count(final.get("paired_available_targets"), "paired_available_targets"),
        "baseline": _method(final.get("baseline"), "baseline"),
        "winner": winner,
        "paired_mae_difference": {
            "value_mgkg": _finite(diff.get("difference_mgkg"), "difference_mgkg"),
            "ci95_mgkg": [_finite(ci[0], "ci95[0]"), _finite(ci[1], "ci95[1]")],
            "bootstrap_draws": _count(diff.get("bootstrap_draws"), "bootstrap_draws"),
            "seed": _count(diff.get("seed"), "seed"),
        },
        "goal": {
            "metric": "exceed_upper",
            "max": goal,
            "kind": "research_target",
            "reference": f"{PROTOCOL} §5",
            "met_by_winner": winner["exceed_upper"] <= goal,
            "met_by_baseline": final["baseline"]["exceed_upper"] <= goal,
        },
        "selection": {
            "frozen_before_period": bool(policy.get("selection_was_frozen")),
            "changed_by_result": bool(policy.get("result_changed_selection_or_parameters")),
            "evidence_sha256": selection.get("evidence_sha256"),
            "development_end": selection.get("development_end"),
        },
        "model_link": {
            "evaluation_fingerprint": policy.get("evaluation_model_fingerprint"),
            "declared_fingerprints": [value for value in
                                      [policy.get("deployed_model_fingerprint_after_metadata_hardening")] if value],
            "note": "Сравнивается с training_fingerprint записи. Совпадение с declared — отпечаток после усиления "
                    "метаданных без повторного прогона 2026; другое значение — метрики к модели записи не относятся.",
        },
        "interpretation": final.get("interpretation"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сводка исследования прогноза для паспорта доказательств")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    summary = build_forecast_summary(args.root)
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
