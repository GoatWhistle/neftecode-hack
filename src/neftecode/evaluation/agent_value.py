"""Same-input comparison of the deterministic core, a simple rule, and an agentic runner."""

from collections.abc import Callable, Iterable
import copy
import time

from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.domain.production.scenario import Scenario
from neftecode.evaluation.benchmark_run import Benchmark, THRESHOLD


def _identity(decision: dict) -> tuple:
    return (decision.get("status"), (decision.get("selected_plan") or {}).get("plan_id"),
            (decision.get("refusal") or {}).get("kind"))


def _sulfur_margin(decision: dict) -> float | None:
    checks = ((decision.get("gate") or {}).get("checks") or ())
    margins = [item["limit"] - item["observed"] for item in checks
               if item.get("constraint_id") == "quality.sulfur_mgkg"
               and isinstance(item.get("limit"), (int, float))
               and isinstance(item.get("observed"), (int, float))]
    return min(margins) if margins else None


def run_agent_value_study(
    cases: Iterable[tuple[str, dict]], *, budget: int,
    scenario_parser: Callable[[dict], Scenario],
    agentic_runner: Callable[[Scenario, dict, int], dict],
    repeats: int = 2,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    if repeats < 2:
        raise ValueError("Для проверки стабильности нужны минимум два повтора")
    records = []
    for name, raw in cases:
        scenario = scenario_parser(copy.deepcopy(raw))
        started = clock()
        core = MakeDecision(scenario).decide(budget=budget)
        core_latency = clock() - started
        threshold = Benchmark(scenario, copy.deepcopy(raw), budget, scenario_parser).run()["strategies"][THRESHOLD]
        agent_runs = []
        latencies = []
        for _ in range(repeats):
            started = clock()
            agent_runs.append(agentic_runner(scenario_parser(copy.deepcopy(raw)), copy.deepcopy(raw), budget))
            latencies.append(clock() - started)
        first = agent_runs[0]
        stable = len({_identity(item) for item in agent_runs}) == 1
        core_feasible = core.get("status") != "refuse"
        agent_refused = first.get("status") == "refuse"
        records.append({
            "case": name,
            "core": {"identity": _identity(core), "cost_per_tonne": core.get("cost_per_tonne"),
                     "sulfur_margin_mgkg": _sulfur_margin(core), "latency_seconds": core_latency},
            "threshold": threshold,
            "agentic": {"identity": _identity(first), "cost_per_tonne": first.get("cost_per_tonne"),
                        "sulfur_margin_mgkg": _sulfur_margin(first),
                        "latency_seconds": latencies, "stable": stable,
                        "provider": (first.get("agentic") or {}).get("provider")},
            "changed_selection": _identity(first) != _identity(core),
            "needless_refusal": bool(agent_refused and core_feasible),
        })
    return {
        "protocol": "same_input_agent_value_v1",
        "repeats": repeats,
        "cases": records,
        "limits": [
            "Изменение выбора не считается пользой само по себе; оцениваются запас, стоимость и отказ.",
            "Scripted provider проверяет протокол, но не доказывает пользу языковой модели.",
            "Малый сценарный набор не является промышленной валидацией.",
        ],
    }
