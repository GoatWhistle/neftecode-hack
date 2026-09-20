"""Fixed blind environments for evaluating recommendations outside the optimizer model."""

from dataclasses import dataclass
import copy
from collections.abc import Callable

from neftecode.evaluation.benchmark_run import Benchmark
from neftecode.domain.production.scenario import Scenario


@dataclass(frozen=True)
class IndependentEnvironment:
    name: str
    response_factor: float
    lag_factor: float
    main_sulfur_factor: float
    reserve_sulfur_factor: float


# Fixed before recommendations are evaluated. These are scenario stresses, not plant estimates.
DEFAULT_INDEPENDENT_ENVIRONMENTS = (
    IndependentEnvironment("nominal", 1.0, 1.0, 1.0, 1.0),
    IndependentEnvironment("slow_weak_response", 0.75, 1.75, 1.05, 1.0),
    IndependentEnvironment("nonideal_mixing", 0.9, 1.25, 1.10, 1.15),
)


def apply_environment(raw: dict, environment: IndependentEnvironment) -> dict:
    altered = copy.deepcopy(raw)
    hydrotreating = altered["stages"]["hydrotreating"]
    hydrotreating["model"]["conversion_per_degree"] *= environment.response_factor
    hydrotreating["response_lag_hours"]["value"] = min(
        3.0, hydrotreating["response_lag_hours"]["value"] * environment.lag_factor
    )
    factors = {"main": environment.main_sulfur_factor,
               "reserve": environment.reserve_sulfur_factor}
    for tank in altered.get("tanks", ()): 
        factor = factors.get(tank.get("tank_id"))
        sulfur = (tank.get("properties") or {}).get("sulfur_mgkg")
        if factor is not None and sulfur is not None:
            sulfur["value"] *= factor
    return altered


def run_independent_study(raw: dict, *, budget: int,
                          scenario_parser: Callable[[dict], Scenario],
                          environments=DEFAULT_INDEPENDENT_ENVIRONMENTS) -> dict:
    optimizer_scenario = scenario_parser(copy.deepcopy(raw))
    results = []
    for environment in environments:
        evaluation_raw = apply_environment(raw, environment)
        benchmark = Benchmark(
            optimizer_scenario, copy.deepcopy(raw), budget=budget,
            scenario_parser=scenario_parser, evaluation_raw=evaluation_raw,
        ).run()
        results.append({
            "environment": environment.name,
            "parameters": {
                "response_factor": environment.response_factor,
                "lag_factor": environment.lag_factor,
                "main_sulfur_factor": environment.main_sulfur_factor,
                "reserve_sulfur_factor": environment.reserve_sulfur_factor,
            },
            "benchmark": benchmark,
        })
    return {
        "protocol": "fixed_hidden_environment_v1",
        "claim": ("Среда оценки отличается от модели, которой выбирался план. Диапазоны сценарные "
                  "и не являются оценкой вероятности или промышленным доказательством."),
        "environments": results,
    }
