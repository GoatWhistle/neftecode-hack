from dataclasses import dataclass, field
import copy
import json
from pathlib import Path
from typing import Callable

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.application.contracts import MEASURED_ORIGIN


DemoRunner = Callable[..., dict]

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

SOURCE_FAULTS = {
    "healthy": {},
    "frozen_pak": {"pak_frozen": True, "pak_usable": False},
    "stale_lab": {"lab_age_hours": 120.0, "lab_usable": False},
    "both_broken": {"lab_value": None, "lab_usable": False, "pak_frozen": True, "pak_usable": False},
    "missing_telemetry": {"telemetry_missing_fraction": 0.9},
}


class DemoError(ValueError):
    pass


def healthy_state() -> dict:
    return {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0,
            "origin": "synthetic_scenario_state"}


def apply_change(raw: dict, change: str, value, target: str | None = None) -> dict:
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
                    if tank.get("on_demand"):
                        raise DemoError(f"{target}: компонент производится по необходимости, запаса у него нет")
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
    if fault not in SOURCE_FAULTS:
        raise DemoError(f"Неизвестный отказ источника «{fault}». "
                        f"Доступно: {', '.join(sorted(SOURCE_FAULTS))}")
    out = {**state, **SOURCE_FAULTS[fault]}
    if fault != "healthy":
        if out.get("origin") != MEASURED_ORIGIN:
            out["origin"] = "injected_source_failure"
        out["injected_fault"] = fault
        out["injection"] = f"Модельная инъекция отказа: {fault}. Это не наблюдение из данных."
    return out


@dataclass
class Demo:

    raw: dict
    runner: DemoRunner
    trust_cfg: dict
    budget: int = DEFAULT_BUDGET
    trust_origin: str | None = None
    changes: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    response_model: dict | None = None

    @classmethod
    def from_path(cls, path, runner: DemoRunner, trust_cfg: dict, budget: int = DEFAULT_BUDGET,
                  trust_origin: str | None = None, snapshots: list | None = None,
                  response_model: dict | None = None) -> "Demo":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), runner, trust_cfg, budget, trust_origin,
                   snapshots=list(snapshots or []), response_model=response_model)

    def reset(self) -> "Demo":
        return Demo(self.raw, self.runner, self.trust_cfg, self.budget, self.trust_origin,
                    snapshots=self.snapshots, response_model=self.response_model)

    def snapshot(self, name: str | None):
        if name in (None, "", "synthetic"):
            return None
        for item in self.snapshots:
            if snapshot_key(item) == name or item.get("label") == name:
                return item
        raise DemoError(f"Срез «{name}» не найден. Доступно: "
                        + ", ".join(snapshot_key(item) for item in self.snapshots) + ", synthetic")

    def run(self, changes=(), fault: str = "healthy", snapshot: str | None = None) -> dict:
        raw = copy.deepcopy(self.raw)
        applied = []
        for change in changes:
            raw = apply_change(raw, change["change"], change.get("value"), change.get("target"))
            applied.append(change)
        chosen = self.snapshot(snapshot)
        base = copy.deepcopy(chosen["state"]) if chosen is not None else healthy_state()
        state = apply_source_failure(base, fault)
        result = self.runner(raw, state, self.budget, self.trust_cfg, trust_origin=self.trust_origin,
                             snapshot=chosen, response_model=self.response_model)
        return {**result, "applied": applied, "fault": fault,
                "snapshot": snapshot_key(chosen) if chosen is not None else None,
                "state_origin": state.get("origin"),
                "injection": state.get("injection"),
                "note": (("Недопустимое изменение отклонено загрузчиком сценария, а не "
                          "исправлено молча.") if result["rejected"] else
                         ("Изменение проведено через тот же загрузчик и то же ядро решения; "
                          "заранее заготовленных ответов здесь нет."))}


def snapshot_title(snapshot: dict) -> str:
    at = snapshot["at"]
    day, clock = at[:10].split("-"), at[11:16]
    label = snapshot.get("label") or "реальный срез"
    return f"{label} · {day[2]}.{day[1]}.{day[0]} {clock}"


def state_origin_label(state: dict, snapshot: dict | None) -> str:
    if snapshot is None:
        return "синтетическое состояние сценария (реальных измерений нет)"
    label = f"реальный срез: {snapshot_title(snapshot)}"
    if snapshot.get("synthetic_edits"):
        label += " — часть измерений затёрта искусственно"
    if state.get("injection"):
        label += " — поверх наложена модельная инъекция отказа"
    return label


def snapshot_key(snapshot: dict) -> str:
    stamp = snapshot["at"].replace("-", "").replace(":", "").replace("T", "-")
    return stamp + ("-synthetic" if snapshot.get("synthetic_edits") else "")


def scenes(path, snapshots: list | None = None) -> list[dict]:
    labels = {item.get("label") for item in snapshots or []}

    def real(label, fault):
        return (label, "healthy") if label in labels else (None, fault)

    normal, normal_fault = real("норма", "healthy")
    frozen, frozen_fault = real("зависший ПАК при работающей установке", "frozen_pak")
    refuse, refuse_fault = real("отказ по данным", "both_broken")
    quality_risk = real("риск по качеству при возврате нагрузки", "healthy")[0]
    items = [
        {"name": "Нормальный режим", "changes": [], "fault": normal_fault, "snapshot": normal,
         "expect": "решение без лишних изменений"},
        {"name": "Ухудшение сырья", "fault": "healthy", "snapshot": None,
         "changes": [{"change": "crude_sulfur_wt_pct", "value": 1.95}],
         "expect": "синтетическая сцена: пересчёт качества притока по модели цепочки; большой запас может сохранить допустимость текущего режима"},
        {"name": "Зависший поточный анализатор", "fault": frozen_fault, "changes": [], "snapshot": frozen,
         "expect": "источник теряет доверие, роль переходит к лаборатории; приток не ниже последнего доверенного показания"},
        {"name": "Устаревшая лаборатория и сломанный анализатор", "fault": refuse_fault,
         "changes": [], "snapshot": refuse, "expect": "отказ по данным"},
        {"name": "Резервуар выведен из работы", "fault": normal_fault, "snapshot": normal,
         "changes": [{"change": "tank_available", "value": False, "target": "reserve"}],
         "expect": "пересчёт без резерва либо отказ"},
    ]
    if quality_risk is not None:
        items.append(
            {"name": "Риск ухудшения качества", "fault": "healthy", "changes": [],
             "snapshot": quality_risk,
             "expect": "реальный срез без инъекций: прогноз серы притока 14.93 мг/кг (верхняя граница 20.94) "
                       "выше предела 10 мг/кг, при сохранении режима смесь выходит за предел через 5 ч — "
                       "раньше запаса реакции 12 ч, поэтому ожидается корректирующая рекомендация, а не hold"})
    return items
