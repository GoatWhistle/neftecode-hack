"""Advisor study on real 2026 data: random moments, sensitivity, all sustained episodes.

Run from the project root:
    uv run python context/experiments/advisor_study_2026-09-15.py random out.jsonl
    uv run python context/experiments/advisor_study_2026-09-15.py sensitivity out.jsonl
    uv run python context/experiments/advisor_study_2026-09-15.py episodes out.jsonl

The decision receives only the moment `at`. Future analyser and laboratory values are read by
`aftermath` after the decision and are stored next to it for evaluation only.
"""
import copy
import json
import pickle
import random
import sys
import time
from pathlib import Path

import pandas as pd

from neftecode.evaluation.episodes import _as_series, classify_episodes, excursion_episodes
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.data.data import _untrusted_runs, load_sources
from neftecode.infrastructure.data.quality import read_quality_series
from neftecode.infrastructure.live.advisor import LiveAdviceAdapter

ROOT = Path(".")
SEED = 20260915
BASE_CONTROLS = None


def load():
    cfg = json.loads((ROOT / "config/experiment.json").read_text())
    bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
    signals, lab, online = load_sources(ROOT / "task")
    series = _as_series(online)
    lab_sulfur = read_quality_series(ROOT / "task")["sulfur_mgkg"].set_index("time").value
    raw = json.loads((ROOT / "config/scenarios/baseline.json").read_text())
    return cfg, bundle, signals, lab, online, series, lab_sulfur, raw


def adapter_for(raw, signals, lab, online, bundle):
    return LiveAdviceAdapter(signals, lab, online, bundle, raw,
                             robustness_evaluator=RobustnessCheck(parse_scenario(raw), raw,
                                                                  scenario_parser=parse_scenario))


def decide(adapter, when, base_controls):
    started = time.time()
    try:
        result = adapter.advise(pd.Timestamp(when).isoformat())
    except Exception as exc:  # recorded, never hidden
        return {"at": pd.Timestamp(when).isoformat(), "exception": repr(exc)}
    decision = result.get("decision") or {}
    action = decision.get("immediate_action") or {}
    look = decision.get("lookahead") or {}
    initial, selected = look.get("initial") or {}, look.get("selected") or {}
    controls = action.get("controls") or {}
    return {
        "at": pd.Timestamp(when).isoformat(),
        "trust_usable": result["trust"].get("usable"), "primary": result["trust"].get("primary"),
        "forecast_model": (result.get("forecast") or {}).get("model"),
        "forecast_upper": (result.get("forecast") or {}).get("upper"),
        "tank": result.get("bound_sulfur_mgkg"), "inflow": result.get("bound_inflow_sulfur_mgkg"),
        "status": decision.get("status"), "error": result.get("error"),
        "refusal": (decision.get("refusal") or {}).get("kind"),
        "recipe": {k: v for k, v in (action.get("recipe") or {}).items() if v},
        "throughput_tph": action.get("throughput_tph"),
        "control_changes": {k: v for k, v in controls.items()
                            if base_controls.get(k) is not None and abs(v - base_controls[k]) > 1e-9},
        "lookahead_initial_h": initial.get("hours_to_violation"),
        "lookahead_selected_h": selected.get("hours_to_violation"),
        "lookahead_stock_h": selected.get("stock_ends_at_hours"),
        "lookahead_switched": look.get("switched"), "lookahead_warning": look.get("warning"),
        "reason": (decision.get("reason") or "")[:240],
        "seconds": round(time.time() - started, 2),
    }


def aftermath(when, series, lab_sulfur):
    """Evaluation only: what the hydrotreated stream did after the decision."""
    when = pd.Timestamp(when)
    out = {}
    window = series[(series.index > when - pd.Timedelta(value=1, unit="h")) & (series.index <= when + pd.Timedelta(value=24, unit="h"))]
    trusted = window[~_untrusted_runs(window)]
    for hours in (12, 24):
        part = trusted[(trusted.index > when) & (trusted.index <= when + pd.Timedelta(value=hours, unit="h"))]
        out[f"pak_max_{hours}h"] = None if part.empty else round(float(part.max()), 3)
        out[f"pak_share_over_10_{hours}h"] = None if part.empty else round(float((part > 10).mean()), 3)
        out[f"pak_hours_over_10_{hours}h"] = None if part.empty else round(float((part > 10).sum()) / 6, 2)
    future_lab = lab_sulfur[(lab_sulfur.index > when) & (lab_sulfur.index <= when + pd.Timedelta(value=24, unit="h"))]
    out["lab_next_24h"] = [[t.isoformat(), float(v)] for t, v in future_lab.items()]
    now = series[series.index <= when]
    out["pak_asof"] = None if now.empty else round(float(now.iloc[-1]), 3)
    return out


def random_moments():
    grid = list(pd.date_range("2026-01-03 00:00", "2026-08-07 00:00", freq="30min"))
    return sorted(random.Random(SEED).sample(grid, 250))


def variants(raw):
    def with_policy(**changes):
        doc = copy.deepcopy(raw)
        doc["policy"].update(changes)
        return doc

    def with_inventory(mass):
        doc = copy.deepcopy(raw)
        for tank in doc["tanks"]:
            if tank["tank_id"] == "main":
                tank["inventory"]["value"] = float(mass)
        return doc

    return {"base": copy.deepcopy(raw),
            "window_24h": with_policy(tank_level_window_hours=24.0),
            "window_72h": with_policy(tank_level_window_hours=72.0),
            "reaction_6h": with_policy(min_reaction_hours=6.0),
            "reaction_24h": with_policy(min_reaction_hours=24.0),
            "tank_2000t": with_inventory(2000),
            "tank_8000t": with_inventory(8000)}


def base_controls(raw):
    return {name: spec["current"]["value"] for stage in raw["stages"].values()
            for name, spec in stage["controls"].items()}


def sustained_2026(series, cfg):
    episodes = classify_episodes(excursion_episodes(series, cfg["sulfur_limit"]), cfg["sustained_exceedance_hours"])
    return episodes[(episodes.kind == "sustained") & (episodes.start >= cfg["calibration_end"])].reset_index(drop=True)


def main():
    command, out_path = sys.argv[1], Path(sys.argv[2])
    cfg, bundle, signals, lab, online, series, lab_sulfur, raw = load()
    controls = base_controls(raw)
    rows = []
    if command == "random":
        adapter = adapter_for(raw, signals, lab, online, bundle)
        for index, when in enumerate(random_moments()):
            rows.append({"index": index, **decide(adapter, when, controls), **aftermath(when, series, lab_sulfur)})
    elif command == "sensitivity":
        retro = [json.loads(line) for line in (ROOT / "context/experiments/retro-episodes-2026-09-15.jsonl").open()]
        moments = [("episode", r["episode"], r["moment"], pd.Timestamp(r["at"])) for r in retro]
        moments += [("random", i, "random", when) for i, when in enumerate(random_moments()[:100])]
        for name, doc in variants(raw).items():
            adapter = adapter_for(doc, signals, lab, online, bundle)
            for kind, ident, label, when in moments:
                rows.append({"variant": name, "kind": kind, "id": ident, "moment": label,
                             **decide(adapter, when, controls), **aftermath(when, series, lab_sulfur)})
    elif command == "episodes":
        adapter = adapter_for(raw, signals, lab, online, bundle)
        for number, row in sustained_2026(series, cfg).iterrows():
            start, end = pd.Timestamp(row.start), pd.Timestamp(row.end)
            part = series[(series.index >= start) & (series.index <= end)]
            frozen_share = float(_untrusted_runs(part).mean()) if len(part) else None
            inside_lab = lab_sulfur[(lab_sulfur.index >= start) & (lab_sulfur.index <= end)]
            label = ("frozen" if frozen_share is not None and frozen_share > 0.5 else
                     "lab_confirmed" if (inside_lab > 10).any() else
                     "lab_not_confirmed" if len(inside_lab) else "no_lab")
            stop = min(end, start + pd.Timedelta(value=24, unit="h"))
            for when in pd.date_range(start - pd.Timedelta(value=12, unit="h"), stop, freq="1h"):
                rows.append({"episode": int(number) + 1, "episode_start": start.isoformat(),
                             "episode_end": end.isoformat(), "duration_h": round(float(row.duration_hours), 2),
                             "peak": round(float(row.peak), 2), "frozen_share": frozen_share, "label": label,
                             "episode_lab": [[t.isoformat(), float(v)] for t, v in inside_lab.items()],
                             "offset_h": round((when - start).total_seconds() / 3600, 2),
                             **decide(adapter, when, controls)})
    else:
        raise SystemExit(f"Неизвестная подкоманда {command}")
    with out_path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(f"{command}: {len(rows)} записей, исключений {sum('exception' in r for r in rows)} -> {out_path}")


if __name__ == "__main__":
    main()
