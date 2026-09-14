"""Build reproducible demo and replay artifacts."""
import json
import pickle

import numpy as np
import pandas as pd

from neftecode.application.services.trust import DataTrustAgent
from neftecode.composition.decision import run_demo_decision
from neftecode.infrastructure.artifacts import clean, write_json
from neftecode.infrastructure.live.advisor import bind_forecast
from neftecode.presentation.reports.experiment import make_report

STATE_COLUMNS = ["decision_time", "lab_sample_time", "lab_available_time", "lab_value", "lab_age_hours",
                 "lab_usable", "pak_sample_time", "pak_value", "pak_age_minutes", "pak_frozen",
                 "pak_conflict", "pak_usable", "telemetry_missing_fraction"]

def forecast_from_row(row, prefix: str, model: str) -> dict:
    """Build the live forecast wire shape from one frozen replay row."""
    value, lower, upper = [clean(row.get(prefix + column))
                           for column in ("prediction", "lower", "upper")]
    values = (lower, value, upper)
    available = (all(isinstance(number, (int, float)) for number in values)
                 and lower <= value <= upper)
    return {"model": model, "value": value if available else None,
            "lower": lower if available else None, "upper": upper if available else None,
            "available": available,
            "reason": ("Замороженный прогноз из тестового периода" if available
                       else "Прогноз недоступен на этом тестовом моменте")}

def risk_from_row(row):
    return {name: {field: clean(row.get(prefix + field)) for field in ("score", "threshold", "model")}
            for name, prefix in [("main", "risk_"), ("fallback", "risk_fallback_")]}

def risk_alarm(reading: dict) -> bool | None:
    score, threshold = reading.get("score"), reading.get("threshold")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and np.isfinite(value) for value in (score, threshold)):
        return None
    return score >= threshold

def make_demo(root, out):
    scenario_dir = root / "config/scenarios"
    baseline = json.loads((scenario_dir / "baseline.json").read_text())
    healthy = {"decision_time": "2026-01-15T10:00:00",
               "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
               "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
               "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0,
               "origin": "synthetic_acceptance_test"}
    normal = bind_forecast(baseline, {
        "model": "synthetic", "value": 6.0, "lower": 4.0, "upper": 8.0,
        "available": True, "reason": "Синтетическая проверка механики решения",
    })
    # The tank already stores sulfur close to the limit, and the incoming stream could be worse.
    near_limit = json.loads(json.dumps(baseline))
    for tank in near_limit["tanks"]:
        if tank["tank_id"] == "main":
            tank["sulfur_from_chain"] = False
            tank["properties"]["sulfur_mgkg"] = {
                "value": 10.7, "unit": "мг/кг", "source": "scenario",
                "note": "Синтетическая проверка: запас резервуара уже близок к пределу."}
    conflict = bind_forecast(near_limit, {
        "model": "synthetic", "value": 12.0, "lower": 10.0, "upper": 14.0,
        "available": True, "reason": "Синтетическая проверка механики решения",
    })
    demos = {
        "normal_synthetic": run_demo_decision(normal, healthy, 400)["decision"],
        "conflict_synthetic": run_demo_decision(conflict, healthy, 400)["decision"],
        "missing_synthetic": run_demo_decision(
            baseline,
            dict(healthy, lab_value=None, lab_usable=False, pak_value=None, pak_usable=False,
                 telemetry_missing_fraction=1),
            400,
        )["decision"],
        "no_feasible_synthetic": run_demo_decision(
            json.loads((scenario_dir / "no_feasible.json").read_text()), healthy, 400
        )["decision"],
    }
    replay_rows = []
    if (out / "predictions.csv").exists():
        frame = pd.read_csv(out / "predictions.csv")
        summary = json.loads((out / "metrics.json").read_text())
        model_cfg = {}
        selected = summary["selected"]
        fallback_model = "catboost_no_pak"
        model_path = out / "model.pkl"
        if model_path.exists():
            with model_path.open("rb") as stream:
                bundle = pickle.load(stream)
            model_cfg = bundle.get("config", {})
            selected = bundle.get("selected", selected)
            fallback_model = bundle.get("fallback", fallback_model)
        unavailable = 0
        for _, row in frame.iterrows():
            # Deliberate allowlist: future target and its actual value NEVER reach agents.
            state = clean({key: row[key] for key in STATE_COLUMNS})
            state["origin"] = "historical_replay_with_synthetic_blending"
            trust = DataTrustAgent(model_cfg).assess(state)
            prefix, model = (("fallback_", fallback_model) if trust.fallback_mode
                             else ("", selected))
            forecast = forecast_from_row(row, prefix, model)
            risk = risk_from_row(row)
            active_risk = risk["fallback" if trust.fallback_mode else "main"]
            if trust.usable and not forecast["available"]:
                unavailable += 1
                replay_rows.append({"decision_time": row.decision_time, "decision_id": None,
                                    "status": "unavailable", "source": trust.primary,
                                    "forecast_model": model,
                                    "risk_model": active_risk["model"],
                                    "risk_alarm": risk_alarm(active_risk)})
                continue
            raw = bind_forecast(baseline, forecast) if trust.usable else baseline
            decision = run_demo_decision(raw, state, 400, trust_cfg=model_cfg)["decision"]
            key = "historical_" + decision["status"]
            if key not in demos:
                demos[key] = decision
            replay_rows.append({"decision_time": row.decision_time, "decision_id": decision["decision_id"],
                                "status": decision["status"], "source": trust.primary,
                                "forecast_model": forecast["model"],
                                "risk_model": active_risk["model"],
                                "risk_alarm": risk_alarm(active_risk)})
        pd.DataFrame(replay_rows).to_csv(out / "replay.csv", index=False)
        summary["replay"] = {
            "n": len(replay_rows),
            "statuses": pd.Series([r["status"] for r in replay_rows]).value_counts().to_dict(),
            "unavailable_forecasts": unavailable,
            "scope": "Работа механизма рекомендаций в синтетическом смешении; не доказательство экономии или безопасности реального выпуска.",
        }
        write_json(out / "metrics.json", summary)
    write_json(out / "demo.json", demos)
    with (out / "audit.jsonl").open("w") as stream:
        for name, decision in demos.items():
            stream.write(json.dumps(clean({"case": name, **decision}), ensure_ascii=False, allow_nan=False) + "\n")
    make_report(out, demos)
    print(f"Готово: {out / 'report.md'}", flush=True)
