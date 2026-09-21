from dataclasses import dataclass, field
from typing import Callable

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.application.conditions import apply_changes, state_under


DemoRunner = Callable[..., dict]


class DemoError(ValueError):
    pass


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
        applied = list(changes)
        raw = apply_changes(self.raw, applied)
        chosen = self.snapshot(snapshot)
        state = state_under(chosen, fault)
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
