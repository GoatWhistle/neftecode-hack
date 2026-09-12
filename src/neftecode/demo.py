"""Changeable demonstration: the jury edits the conditions, the core recomputes.

The requirement this satisfies is narrow and strict: an arbitrary admissible change must reach
the calculation, not switch between prepared answers. So a change here is an edit of the
scenario document, which is then parsed by the same loader with the same validation, and run
through the same orchestrator. There is no branch in this module that returns a stored text.

Consequences kept on purpose:

* an inadmissible change is rejected by the scenario loader with its own message — the demo
  does not silently repair it;
* an injected failure (a frozen analyser, an unavailable tank) is labelled as an injection, so
  nobody mistakes it for something observed in the data;
* the original scenario is always recoverable, because every change is applied to a fresh copy.
"""
from dataclasses import dataclass, field
import copy
import json
from pathlib import Path

from .explain import explain
from .inventory import initial_state
from .orchestrator import Orchestrator
from .scenario import Scenario, ScenarioError, parse_scenario
from .trust import DataTrustAgent
from .ui import Screen, error_payload

#: What the jury may change, and where it lands in the scenario document.
CHANGES = {
    "crude_sulfur_wt_pct": ("crude", "Сера сырья, % масс."),
    "product_sulfur_mgkg": ("product", "Предел серы продукта, мг/кг"),
    "product_t95_c": ("product", "Предел T95, °C"),
    "product_cetane_number": ("product", "Минимум цетанового числа"),
    "tank_inventory": ("tanks", "Запас резервуара, т"),
    "tank_available": ("tanks", "Доступность резервуара"),
    "throughput_tph": ("current_operation", "Текущий выпуск, т/ч"),
    "source_failure": ("state", "Исправность источников данных"),
}

#: Data faults the jury can inject. They are model injections, never observations.
SOURCE_FAULTS = {
    "healthy": {},
    "frozen_pak": {"pak_frozen": True, "pak_usable": False},
    "stale_lab": {"lab_age_hours": 120.0, "lab_usable": False},
    "both_broken": {"lab_value": None, "lab_usable": False, "pak_frozen": True, "pak_usable": False},
    "missing_telemetry": {"telemetry_missing_fraction": 0.9},
}


class DemoError(ValueError):
    """Raised when a requested change is not one the demo offers."""


def healthy_state() -> dict:
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0,
            "origin": "synthetic_scenario_state"}


def apply_change(raw: dict, change: str, value, target: str | None = None) -> dict:
    """Apply one change to a COPY of the scenario. The original is never touched."""
    if change not in CHANGES:
        raise DemoError(f"Демонстрация не умеет менять «{change}». "
                        f"Доступно: {', '.join(sorted(CHANGES))}")
    out = copy.deepcopy(raw)
    if change == "crude_sulfur_wt_pct":
        out["crude"]["sulfur_wt_pct"]["value"] = value
    elif change.startswith("product_"):
        key = change[len("product_"):]
        if out["product"].get(key) is None:
            raise DemoError(f"Показатель {key} в сценарии не задан, менять нечего")
        out["product"][key]["value"] = value
    elif change in ("tank_inventory", "tank_available"):
        if not target:
            raise DemoError(f"{change}: нужно указать резервуар")
        for tank in out["tanks"]:
            if tank["tank_id"] == target:
                if change == "tank_inventory":
                    tank["inventory"]["value"] = value
                else:
                    tank["available"] = bool(value)
                    tank["note"] = ("Недоступность резервуара — инъекция условий демонстрации, "
                                    "а не наблюдение из данных.")
                break
        else:
            raise DemoError(f"Резервуар {target} не описан в сценарии")
    elif change == "throughput_tph":
        out["current_operation"]["throughput"]["value"] = value
    return out


def apply_source_failure(state: dict, fault: str) -> dict:
    """Inject a data fault, labelled as an injection."""
    if fault not in SOURCE_FAULTS:
        raise DemoError(f"Неизвестный отказ источника «{fault}». "
                        f"Доступно: {', '.join(sorted(SOURCE_FAULTS))}")
    out = {**state, **SOURCE_FAULTS[fault]}
    if fault != "healthy":
        out["origin"] = "injected_source_failure"
        out["injection"] = f"Модельная инъекция отказа: {fault}. Это не наблюдение из данных."
    return out


@dataclass
class Demo:
    """Holds the original scenario and recomputes from it after every change."""

    raw: dict
    budget: int = 400
    changes: list = field(default_factory=list)

    @classmethod
    def from_path(cls, path, budget: int = 400) -> "Demo":
        return cls(json.loads(Path(path).read_text()), budget)

    def reset(self) -> "Demo":
        """Back to the original conditions. Nothing accumulated is kept."""
        return Demo(self.raw, self.budget)

    def run(self, changes=(), fault: str = "healthy") -> dict:
        """Apply the changes to a fresh copy, then run the same core on the result."""
        raw = copy.deepcopy(self.raw)
        applied = []
        for change in changes:
            raw = apply_change(raw, change["change"], change.get("value"), change.get("target"))
            applied.append(change)
        try:
            scenario = parse_scenario(raw)
        except ScenarioError as exc:
            return {"ok": False, "rejected": True, "reason": str(exc), "applied": applied,
                    "screen": error_payload(str(exc)),
                    "note": "Недопустимое изменение отклонено загрузчиком сценария, а не исправлено молча."}
        state = apply_source_failure(healthy_state(), fault)
        decision = Orchestrator(scenario).decide(state=state, budget=self.budget, raw_scenario=raw)
        trust = DataTrustAgent({}).assess(state)
        screen = Screen(decision, explain(decision, scenario),
                        inventories={k: v.inventory_t for k, v in initial_state(scenario).items()},
                        sources=[v.to_dict() for v in trust.sources.values()]).payload()
        return {
            "ok": True, "rejected": False, "applied": applied, "fault": fault,
            "scenario_id": scenario.scenario_id,
            "decision": decision, "screen": screen,
            "injection": state.get("injection"),
            "note": ("Изменение проведено через тот же загрузчик и то же ядро решения; "
                     "заранее заготовленных ответов здесь нет."),
        }


def scenes(path) -> list[dict]:
    """The four scenes the brief requires, expressed as changes rather than as canned answers."""
    return [
        {"name": "Нормальный режим", "changes": [], "fault": "healthy",
         "expect": "решение без лишних изменений"},
        {"name": "Ухудшение сырья", "fault": "healthy",
         "changes": [{"change": "crude_sulfur_wt_pct", "value": 1.95}],
         "expect": "план или отказ по расчёту"},
        {"name": "Зависший поточный анализатор", "fault": "frozen_pak", "changes": [],
         "expect": "источник теряет доверие, роль переходит к лаборатории"},
        {"name": "Устаревшая лаборатория и сломанный анализатор", "fault": "both_broken",
         "changes": [], "expect": "отказ по данным"},
        {"name": "Резервуар выведен из работы", "fault": "healthy",
         "changes": [{"change": "tank_available", "value": False, "target": "reserve"}],
         "expect": "пересчёт без резерва либо отказ"},
    ]
