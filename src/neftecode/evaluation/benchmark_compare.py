from collections.abc import Callable

from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.domain.production.scenario import Scenario

from .benchmark_run import (ADVISOR, ADVISOR_NO_TERMINAL, ADVISOR_NO_TRANSITION, Benchmark, HOLD,
                           STRATEGIES, THRESHOLD)


def compare(scenarios: list[tuple[Scenario, dict]], budget: int = DEFAULT_BUDGET,
            scenario_parser: Callable[[dict], Scenario] | None = None) -> dict:
    per_scenario = [Benchmark(scenario, raw, budget, scenario_parser).run()
                    for scenario, raw in scenarios]
    totals: dict[str, dict] = {name: {"feasible": 0, "refused": 0, "violations": 0,
                                      "production_t": 0.0, "scenarios": 0}
                               for name in STRATEGIES}
    for record in per_scenario:
        for name, result in record["strategies"].items():
            bucket = totals[name]
            bucket["scenarios"] += 1
            if result.get("refused"):
                bucket["refused"] += 1
                continue
            bucket["feasible"] += 1 if result["feasible"] else 0
            bucket["violations"] += result["violations"]
            bucket["production_t"] += result["production_t"] if result["feasible"] else 0.0
    wins, losses = _wins_and_losses(per_scenario)
    return {
        "ablations": _ablations(per_scenario),
        "scenarios": per_scenario,
        "totals": totals,
        "wins": wins,
        "losses": losses,
        "aggregation": "Все сценарии входят в итог. Исключать неудачные случаи ради среднего нельзя.",
        "limits": [
            "Числа получены в нашей сценарной модели и не являются экономией реального завода.",
            "Советчик сравнивается внутри той же модели, против которой он оптимизирует; "
            "проверка на структурно иной среде этим экспериментом не сделана.",
            "Пороговое правило получает те же жёсткие проверки и тот же перебор долей резерва: "
            "заведомо слабый соперник не строился.",
            "Набор сценариев мал и выбран нами; это не оценка на новых условиях.",
            "Выпуск стоит первым в правиле выбора: преимущество этой метрики заложено почти по построению, "
            "но при ограниченном бюджете поиска выигрыш не гарантируется. Поэтому отдельно сравниваются "
            "стоимость на тонну, расход резерва и число "
            "изменений режима. Проигрыши по ним перечислены наравне с выигрышами.",
        ],
    }


def _ablations(per_scenario) -> list[dict]:
    out = []
    for record in per_scenario:
        strategies = record["strategies"]
        full = strategies.get(ADVISOR, {})
        if full.get("refused"):
            continue
        for name, what in ((ADVISOR_NO_TRANSITION, "план во времени"),
                           (ADVISOR_NO_TERMINAL, "правило остатка на конце горизонта")):
            other = strategies.get(name, {})
            if other.get("refused"):
                out.append({"scenario_id": record["scenario_id"], "ablation": what,
                            "effect": "без этой части допустимого плана не находится"})
                continue
            delta = full["production_t"] - other["production_t"]
            if abs(delta) < 1e-9:
                effect = "выпуск не изменился"
            elif delta > 0:
                effect = f"эта часть добавляет {delta:.0f} т выпуска"
            else:
                effect = (f"без этой части выпуск на {-delta:.0f} т выше: ограничение стоит выпуска, "
                          f"и это его цена, а не недостаток")
            out.append({"scenario_id": record["scenario_id"], "ablation": what,
                        "production_with": full["production_t"],
                        "production_without": other["production_t"], "effect": effect})
    return out


DIMENSIONS = (
    ("production_t", "выпуск", "больше"),
    ("cost_per_tonne", "стоимость на тонну", "меньше"),
    ("reserve_used_t", "расход резерва", "меньше"),
    ("changes", "число изменений режима", "меньше"),
)


def _better(name: str, a: float, b: float) -> bool:
    direction = next(d for key, _, d in DIMENSIONS if key == name)
    return a > b + 1e-9 if direction == "больше" else a < b - 1e-9


def _wins_and_losses(per_scenario) -> tuple[list, list]:
    wins, losses = [], []
    for record in per_scenario:
        strategies = record["strategies"]
        advisor = strategies.get(ADVISOR, {})
        if advisor.get("refused"):
            simple_ok = [n for n in (HOLD, THRESHOLD)
                         if not strategies[n].get("refused") and strategies[n]["feasible"]]
            (losses if simple_ok else wins).append({
                "scenario_id": record["scenario_id"],
                "note": ("Советчик отказался там, где простое правило нашло допустимый вариант"
                         if simple_ok else
                         "Допустимого варианта нет ни у кого; отказ — правильный ответ")})
            continue
        for name in (HOLD, THRESHOLD):
            other = strategies[name]
            if other.get("refused"):
                wins.append({"scenario_id": record["scenario_id"], "beats": name,
                             "dimension": "выполнимость", "note": "соперник не дал варианта"})
                continue
            if not other["feasible"] and advisor["feasible"]:
                wins.append({"scenario_id": record["scenario_id"], "beats": name,
                             "dimension": "соблюдение ограничений",
                             "note": f"{name} нарушает ограничения в {other['violations']} проверках"})
                continue
            if other["feasible"] and not advisor["feasible"]:
                losses.append({"scenario_id": record["scenario_id"], "loses_to": name,
                               "dimension": "соблюдение ограничений"})
                continue
            if not other["feasible"]:
                continue
            for key, label, direction in DIMENSIONS:
                mine, theirs = advisor.get(key), other.get(key)
                if mine is None or theirs is None:
                    continue
                if _better(key, mine, theirs):
                    wins.append({"scenario_id": record["scenario_id"], "beats": name,
                                 "dimension": label, "advisor": mine, "other": theirs})
                elif _better(key, theirs, mine):
                    losses.append({"scenario_id": record["scenario_id"], "loses_to": name,
                                   "dimension": label, "advisor": mine, "other": theirs,
                                   "note": f"{label}: у советчика {mine:g}, у {name} {theirs:g} "
                                           f"(лучше {direction})"})
    return wins, losses
