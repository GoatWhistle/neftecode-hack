from dataclasses import dataclass
import math

from neftecode.application.contracts import MEASURED_ORIGIN
from neftecode.domain.production.scenario import Scenario


BAD_DATA = "bad_data"
MODEL_NOT_APPLICABLE = "model_not_applicable"
NO_FEASIBLE_PLAN = "no_feasible_plan"
REFUSAL_KINDS = (BAD_DATA, MODEL_NOT_APPLICABLE, NO_FEASIBLE_PLAN)

LAB_DELAY_HOURS = 4.0


class ExplanationError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Evidence:

    kind: str
    ref: str
    value: float | None = None
    detail: str | None = None

    KINDS = ("observation", "scenario", "model", "gate_check", "policy")

    def __post_init__(self):
        if self.kind not in self.KINDS:
            raise ExplanationError(f"Неизвестный вид ссылки: {self.kind}")
        if not self.ref or not self.ref.strip():
            raise ExplanationError("Ссылка обязана называть источник")
        if self.value is None and not self.detail:
            raise ExplanationError(f"Ссылка на {self.ref} пуста: нужно значение или пояснение")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "value": self.value, "detail": self.detail}


@dataclass(frozen=True)
class Statement:

    topic: str
    text: str
    value: float | None
    evidence: tuple[Evidence, ...]

    def __post_init__(self):
        if not self.evidence:
            raise ExplanationError(f"{self.topic}: утверждение без ссылки запрещено")
        if self.value is not None:
            matching = [e for e in self.evidence
                        if e.value is not None and abs(e.value - self.value) < 1e-6]
            if not matching:
                raise ExplanationError(
                    f"{self.topic}: число {self.value} в утверждении не совпадает ни с одной ссылкой")

    def to_dict(self) -> dict:
        return {"topic": self.topic, "text": self.text, "value": self.value,
                "evidence": [e.to_dict() for e in self.evidence]}


def operating_margin_warnings(decision: dict, scenario: Scenario) -> list[dict]:
    margin = (scenario.policy or {}).get("sulfur_operating_margin_mgkg")
    checks = [c for c in ((decision.get("gate") or {}).get("checks") or [])
              if c.get("constraint_id") == "quality.sulfur_mgkg" and c.get("observed") is not None
              and c.get("limit") is not None]
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or not checks:
        return []
    worst = max(checks, key=lambda c: c["observed"])
    left = worst["limit"] - worst["observed"]
    if left >= margin:
        return []
    return [{"kind": "sulfur_operating_margin",
             "text": (f"Запас по сере {left:.2f} мг/кг на {worst['time_hours']:g} ч меньше технологического "
                      f"{margin:g} мг/кг, который держат на установке (Q&A 15.09). Предел 10 мг/кг не нарушен, "
                      f"но неопределённость прогноза может съесть такой запас."),
             "observed_margin_mgkg": round(left, 3), "operating_margin_mgkg": margin}]


def current_operation_view(decision: dict, scenario: Scenario, state: dict | None = None) -> dict:
    real = bool(state) and state.get("origin") == MEASURED_ORIGIN
    confirmed = decision.get("current_operation")
    if confirmed:
        view = dict(confirmed)
        view["origin"] = {"controls": {name: "decision" for name in (confirmed.get("controls") or {})},
                          "recipe": "decision", "throughput_tph": "decision", "additive_dose": "decision"}
    else:
        controls, origin = {}, {}
        for stage in scenario.stages.values():
            for name, spec in stage.controls.items():
                current = spec["current"]
                if current.measured or not real:
                    controls[name], origin[name] = current.value, current.source
                else:
                    controls[name], origin[name] = None, "unknown"
        view = {"controls": controls, "recipe": dict(scenario.current_operation.recipe),
                "throughput_tph": scenario.current_operation.throughput.value, "additive_dose": 0.0,
                "origin": {"controls": origin, "recipe": "scenario", "throughput_tph": "scenario",
                           "additive_dose": "scenario"}}
    if real:
        view["measurements"] = {tag: (dict(item) if isinstance(item, dict) else None)
                                for tag, item in (state.get("measurements") or {}).items()}
    return view
