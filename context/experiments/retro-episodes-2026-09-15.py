import json
import pickle
import sys
import time
from pathlib import Path

import pandas as pd

from neftecode.evaluation.episodes import _as_series, classify_episodes, excursion_episodes
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.data.data import load_sources
from neftecode.infrastructure.live.advisor import LiveAdviceAdapter

ROOT = Path(".")
OUT = Path(sys.argv[1])
cfg = json.loads((ROOT / "config/experiment.json").read_text())
bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
signals, lab, online = load_sources(ROOT / "task")
series = _as_series(online)
episodes = classify_episodes(excursion_episodes(series, cfg["sulfur_limit"]), cfg["sustained_exceedance_hours"])
chosen = episodes[(episodes.kind == "sustained") & (episodes.start >= cfg["calibration_end"])].head(10)

raw = json.loads((ROOT / "config/scenarios/baseline.json").read_text())
adapter = LiveAdviceAdapter(signals, lab, online, bundle, raw,
                            robustness_evaluator=RobustnessCheck(parse_scenario(raw), raw,
                                                                 scenario_parser=parse_scenario))

moments = []
for number, row in enumerate(chosen.itertuples(), 1):
    start = pd.Timestamp(row.start)
    for label, when in (("start-2h", start - pd.Timedelta(hours=2)), ("start", start),
                        ("start+2h", start + pd.Timedelta(hours=2)), ("control-7d", start - pd.Timedelta(days=7))):
        moments.append((number, row, label, when))

with OUT.open("w") as stream:
    for number, row, label, when in moments:
        t0 = time.time()
        pak_now = series.asof(when)
        try:
            result = adapter.advise(when.isoformat())
            decision = result.get("decision") or {}
            action = decision.get("immediate_action") or {}
            record = {
                "episode": number, "episode_start": str(row.start), "episode_end": str(row.end),
                "duration_h": round(row.duration_hours, 2), "peak": round(row.peak, 2),
                "moment": label, "at": when.isoformat(), "pak_asof": None if pd.isna(pak_now) else round(float(pak_now), 3),
                "trust_usable": result["trust"].get("usable"), "primary": result["trust"].get("primary"),
                "trust_reasons": result["trust"].get("reasons"),
                "forecast": result["forecast"], "error": result.get("error"),
                "status": decision.get("status"), "reason": decision.get("reason"),
                "recipe": action.get("recipe"), "throughput_tph": action.get("throughput_tph"),
                "controls": action.get("controls"), "additive_dose": action.get("additive_dose"),
                "production_t": decision.get("production_t"), "cost_per_tonne": decision.get("cost_per_tonne"),
                "refusal": decision.get("refusal"),
                "robustness": {k: (decision.get("robustness") or {}).get(k) for k in ("held", "perturbations_evaluated", "fragile")},
                "bound_sulfur": result.get("bound_sulfur_mgkg"), "seconds": round(time.time() - t0, 1),
            }
        except Exception as exc:  # record, never hide
            record = {"episode": number, "moment": label, "at": when.isoformat(), "exception": repr(exc)}
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        print(number, label, when, record.get("status"), record.get("exception") or record.get("error") or "", flush=True)
