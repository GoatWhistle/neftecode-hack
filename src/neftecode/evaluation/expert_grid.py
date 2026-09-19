from collections.abc import Callable
from dataclasses import dataclass
import time

DemoRun = Callable[..., dict]

AXES = {
    "crude_sulfur_wt_pct": (0.3, 1.2, 1.95, 3.0, 5.0),
    "product_sulfur_mgkg": (3.0, 8.0, 10.0, 50.0),
    "product_t95_c": (330.0, 360.0, 380.0),
    "product_cetane_number": (45.0, 51.0, 55.0),
    "throughput_tph": (20.0, 100.0, 220.0, 300.0),
    "tank_inventory": (0.0, 500.0, 4000.0, 20000.0),
    "tank_available": (False, True),
}

FAULTS = ("healthy", "frozen_pak", "stale_lab", "missing_telemetry", "both_broken")

PAIRS = (
    (("crude_sulfur_wt_pct", 5.0), ("product_sulfur_mgkg", 3.0)),
    (("crude_sulfur_wt_pct", 5.0), ("throughput_tph", 300.0)),
    (("crude_sulfur_wt_pct", 1.95), ("tank_available", False)),
    (("tank_inventory", 0.0), ("throughput_tph", 300.0)),
    (("product_sulfur_mgkg", 3.0), ("tank_available", False)),
    (("throughput_tph", 300.0), ("tank_inventory", 0.0)),
)


class GridError(ValueError):
    pass


def _targets(raw: dict) -> dict[str, str]:
    stocked = [t["tank_id"] for t in raw.get("tanks", ()) if not t.get("on_demand")]
    if not stocked:
        raise GridError("В сценарии нет резервуаров с запасом: крутить нечего")
    reserve = [t["tank_id"] for t in raw.get("tanks", ()) if t["tank_id"] != stocked[0]]
    return {"tank_inventory": stocked[0],
            "tank_available": reserve[0] if reserve else stocked[0]}


def _changes(raw: dict) -> list[list[dict]]:
    targets = _targets(raw)
    single = [[{"change": knob, "value": value, "target": targets.get(knob)}]
              for knob, values in AXES.items() for value in values]
    pairs = [[{"change": knob, "value": value, "target": targets.get(knob)} for knob, value in pair]
             for pair in PAIRS]
    return single + pairs


def _label(changes) -> str:
    return "; ".join(f"{c['change']}={c['value']}" + (f"@{c['target']}" if c.get("target") else "")
                     for c in changes) or "без изменений"


def _row(run: DemoRun, changes, fault: str) -> dict:
    started = time.perf_counter()
    row = {"changes": _label(changes), "fault": fault}
    try:
        result = run(changes=changes, fault=fault)
    except ValueError as exc:
        row.update(outcome="rejected_by_demo", reason=str(exc), error=None)
        row["seconds"] = round(time.perf_counter() - started, 3)
        return row
    except Exception as exc:  # noqa: BLE001
        row.update(outcome="traceback", reason=None,
                   error=f"{type(exc).__name__}: {exc}")
        row["seconds"] = round(time.perf_counter() - started, 3)
        return row
    row["seconds"] = round(time.perf_counter() - started, 3)
    if result.get("rejected"):
        row.update(outcome="rejected_by_loader", reason=result.get("reason"), error=None)
        return row
    decision = result["decision"]
    lookahead = decision.get("lookahead") or {}
    offspec = lookahead.get("offspec") or {}
    row.update(
        outcome=decision["status"],
        reason=decision["reason"],
        error=None,
        plan_id=(decision.get("selected_plan") or {}).get("plan_id"),
        production_t=decision.get("production_t"),
        cost_per_tonne=decision.get("cost_per_tonne"),
        severity_index=decision.get("severity_index"),
        rework_cost=offspec.get("rework_cost"),
        plan_extra_cost=offspec.get("plan_extra_cost"),
    )
    return row


@dataclass
class ExpertGrid:

    demo_run: DemoRun
    raw: dict
    scenario_id: str

    def run(self, progress: Callable[[str], None] | None = None) -> dict:
        rows = [_row(self.demo_run, [], fault) for fault in FAULTS]
        if progress is not None:
            progress(f"{self.scenario_id}: отказы источников — {len(rows)}")
        for changes in _changes(self.raw):
            rows.append(_row(self.demo_run, changes, "healthy"))
            if progress is not None and len(rows) % 10 == 0:
                progress(f"{self.scenario_id}: {len(rows)} комбинаций")
        return summarise(self.scenario_id, rows)


def summarise(scenario_id: str, rows: list[dict]) -> dict:
    times = [r["seconds"] for r in rows if r.get("seconds") is not None]
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[row["outcome"]] = statuses.get(row["outcome"], 0) + 1
    costs = [r["cost_per_tonne"] for r in rows
             if isinstance(r.get("cost_per_tonne"), (int, float))]
    severities = [r["severity_index"] for r in rows
                  if isinstance(r.get("severity_index"), (int, float))]
    return {
        "scenario_id": scenario_id,
        "combinations": len(rows),
        "tracebacks": [r for r in rows if r["outcome"] == "traceback"],
        "statuses": dict(sorted(statuses.items())),
        "seconds": {"max": max(times) if times else None,
                    "median": sorted(times)[len(times) // 2] if times else None},
        "cost_per_tonne": {"min": min(costs) if costs else None, "max": max(costs) if costs else None},
        "severity_index": {"min": min(severities) if severities else None,
                           "max": max(severities) if severities else None},
        "rows": rows,
    }


def totals(per_scenario: list[dict]) -> dict:
    tracebacks = [t for record in per_scenario for t in record["tracebacks"]]
    times = [record["seconds"]["max"] for record in per_scenario
             if record["seconds"]["max"] is not None]
    return {
        "scenarios": len(per_scenario),
        "combinations": sum(record["combinations"] for record in per_scenario),
        "tracebacks": len(tracebacks),
        "traceback_examples": [{"scenario_id": r.get("scenario_id"), "changes": r["changes"],
                                "error": r["error"]} for r in tracebacks[:10]],
        "worst_seconds": max(times) if times else None,
        "criterion": ("Ни одна комбинация панели не даёт трейсбек"
                      if not tracebacks else
                      f"НАРУШЕНО: трейсбеков {len(tracebacks)}"),
        "limits": [
            "Сетка идёт на синтетическом состоянии сценария; реальные срезы здесь не проверяются.",
            "Отказ загрузчика на недопустимом условии — правильный исход, а не дефект.",
            "Время измерено на этой машине при бюджете поиска сетки; на другой оно будет другим.",
        ],
    }
