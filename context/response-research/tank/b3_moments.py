"""T110 (б): что меняют варианты в живом решении на моментах config/snapshot_moments.json.

src не меняется: оценка резервуара подменяется в процессе скрипта (monkeypatch `estimate_tank_sulfur`).
Режимы:
  base  — как в src;
  R20   — к оценке по ПАК добавлена причинная медиана последних 20 пар ЛИМС−ПАК, известных к моменту;
  U     — к оценке по ПАК добавлена неопределённость смещения u (b2: q90 |медианы 20 пар| до 2026), консервативно.
Печатает статус, серу резервуара, серу смеси в худшей точке, запас до 10 и время до нарушения за горизонтом.

Запуск из корня основного репозитория (только без LLM):
  AGENTIC_DECISION_ENABLED=0 PYTHONPATH=src .venv/bin/python context/response-research/tank/b3_moments.py
"""
import json
import os
import pickle
import sys
from pathlib import Path

import pandas as pd

assert os.environ.get("AGENTIC_DECISION_ENABLED") == "0", "запуск только с AGENTIC_DECISION_ENABLED=0"
ROOT = Path(os.environ.get("NEFTECODE_ROOT", "."))
HERE = Path(__file__).resolve().parent / "out"  # сырые пары и таблицы не коммитятся (../.gitignore)
sys.path.insert(0, str(ROOT / "src"))
import neftecode.infrastructure.live.advisor as adv  # noqa: E402
from neftecode.evaluation.robustness import RobustnessCheck  # noqa: E402
from neftecode.infrastructure.agentic import default_decision_factory  # noqa: E402
from neftecode.infrastructure.config.scenario import parse_scenario  # noqa: E402
from neftecode.infrastructure.data.data import load_sources  # noqa: E402

bundle = pickle.load((ROOT / "artifacts/model.pkl").open("rb"))
cfg = bundle["config"]
U = json.loads((HERE / "b2_variants.json").read_text())["V2_uncertainty_u_mgkg"]["q90_abs_roll20_pre2026"]
pairs = pd.read_csv(HERE / "b1_pairs.csv", parse_dates=["time"])
pairs = pairs[pairs.pak.notna() & ~pairs.conflict]
DELAY = pd.Timedelta(hours=float(cfg.get("lab_delay_hours", 4)))


def roll20(at: pd.Timestamp) -> float:
    known = pairs[pairs.time + DELAY <= at].d
    return float(known.tail(20).median()) if len(known) >= 5 else 0.0


original = adv.estimate_tank_sulfur
signals, lab, online = load_sources(ROOT / "task", cfg["train_end"])
raw = json.loads((ROOT / "config/scenarios/baseline.json").read_text())
moments = json.loads((ROOT / "config/snapshot_moments.json").read_text())
rows = []
for m in moments:
    if m.get("synthetic_missing"):
        continue
    at = pd.Timestamp(m["at"])
    offsets = {"base": 0.0, "R20": roll20(at), "U": U}
    for mode, off in offsets.items():
        def patched(raw_, state, _off=off):
            lvl = original(raw_, state)
            if lvl["source"] == "pak":
                lvl = {**lvl, "value": lvl["value"] + _off}
            return lvl
        adv.estimate_tank_sulfur = patched
        advisor = adv.LiveAdviceAdapter(
            signals, lab, online, bundle, raw,
            robustness_factory=lambda s, r: RobustnessCheck(s, r, scenario_parser=parse_scenario),
            decision_factory=default_decision_factory(),
            response_model=adv.load_response_model(ROOT),
            coverage=adv.interval_coverage(ROOT / "artifacts", bundle))
        res = advisor.advise(m["at"])
        dec = res.get("decision") or {}
        checks = [c for c in (dec.get("gate") or {}).get("checks") or []
                  if c.get("constraint_id") == "quality.sulfur_mgkg" and c.get("observed") is not None]
        worst = max((c["observed"] for c in checks), default=None)
        la = ((dec.get("lookahead") or {}).get("selected") or {})
        rows.append({"at": m["at"], "label": m["label"], "mode": mode, "offset": round(off, 3),
                     "status": dec.get("status") or "нет решения",
                     "plan": (dec.get("selected_plan") or {}).get("plan_id") if isinstance(dec.get("selected_plan"), dict) else dec.get("selected_plan"),
                     "tank": res.get("bound_sulfur_mgkg"), "inflow": res.get("bound_inflow_sulfur_mgkg"),
                     "worst_sulfur": None if worst is None else round(worst, 3),
                     "margin_to_10": None if worst is None else round(10 - worst, 3),
                     "hours_to_violation": la.get("hours_to_violation"),
                     "decision_id": dec.get("decision_id"), "error": res.get("error")})
        print(rows[-1], flush=True)
adv.estimate_tank_sulfur = original
(HERE / "b3_moments.json").write_text(json.dumps({"u": U, "rows": rows}, ensure_ascii=False, indent=1))
