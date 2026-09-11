"""Explicit roles with a veto/replan cycle; all physical blending limits are scenario inputs."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from .claims import Ledger, measurement, model_result, scenario_input


@dataclass(frozen=True)
class Forecast:
    value: float | None
    lower: float | None
    upper: float | None
    model: str

    def __post_init__(self):
        for name in ("value", "lower", "upper"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                object.__setattr__(self, name, None)


class DataAgent:
    def assess(self, state: dict) -> dict:
        lab = bool(state.get("lab_usable", False))
        pak = bool(state.get("pak_usable", False))
        reasons = []
        if state.get("pak_frozen"):
            pak = False
            reasons.append("ПАК не меняется: подозрение на зависание")
        if state.get("pak_conflict"):
            pak = False
            reasons.append("ПАК расходится с ЛИМС на момент той же пробы")
        if not lab:
            reasons.append("Нет доступного свежего ЛИМС")
        if not pak:
            reasons.append("ПАК недоступен или не прошел проверку")
        missing = state.get("telemetry_missing_fraction", 1)
        if not isinstance(missing, (int, float)) or not math.isfinite(missing) or not 0 <= missing <= .1:
            reasons.append("Недостаточно свежей телеметрии")
            return {"usable": False, "source": None, "fallback": True, "reasons": reasons}
        return {"usable": lab or pak, "source": "ЛИМС" if lab else "ПАК" if pak else None,
                "fallback": not pak, "reasons": reasons}


class QualityAgent:
    @staticmethod
    def assess_risk(reading: dict | None) -> dict:
        reading = reading or {}
        score, threshold = reading.get("score"), reading.get("threshold")
        valid = all(isinstance(v, (int, float)) and math.isfinite(v) for v in (score, threshold))
        return {"model": reading.get("model"), "score": score if valid else None,
                "threshold": threshold if valid else None, "available": valid,
                "alarm": score >= threshold if valid else None,
                "scope": "Дополнительное обнаружение превышения после гидроочистки; не разрешение выпуска смеси"}

    @staticmethod
    def valid_forecast(forecast: Forecast) -> bool:
        values = (forecast.lower, forecast.value, forecast.upper)
        return all(v is not None and math.isfinite(v) for v in values) and 0 <= values[0] <= values[1] <= values[2]

    def assess(self, forecast: Forecast, fraction: float, cfg: dict) -> dict:
        upper = (1 - fraction) * forecast.upper + fraction * cfg["reserve_sulfur_upper"]
        lower = (1 - fraction) * forecast.lower + fraction * cfg["reserve_sulfur_lower"]
        return {"allowed": upper <= cfg["sulfur_limit"], "sulfur_lower": lower,
                "sulfur_upper": upper, "margin": cfg["sulfur_limit"] - upper}


class ReliabilityAgent:
    def assess(self, fraction: float, throughput: float, cfg: dict) -> dict:
        flow = fraction * throughput
        reasons = []
        if not 0 <= fraction <= cfg["max_reserve_fraction"]:
            reasons.append("Доля резерва вне диапазона сценария")
        if abs(fraction - cfg["current_reserve_fraction"]) > cfg["max_fraction_step"] + 1e-9:
            reasons.append("Слишком большое изменение доли за один шаг")
        if not cfg["min_throughput_tph"] <= throughput <= cfg["max_throughput_tph"]:
            reasons.append("Расход смеси вне диапазона сценария")
        if flow > cfg["reserve_available_tph"] + 1e-9:
            reasons.append("Не хватает резервного компонента")
        if flow > cfg["reserve_pump_limit_tph"] + 1e-9:
            reasons.append("Превышен предел насоса резервного компонента")
        return {"allowed": not reasons, "reasons": reasons,
                "pump_load": flow / cfg["reserve_pump_limit_tph"]}


class MarginAgent:
    """Turns the batch trend into the operator's two numbers: time left, window left."""

    URGENCY = {"already_above": "critical", "approaching": "act_now",
               "beyond_horizon": "watch", "no_trend_to_limit": "calm", "unknown": "unknown"}

    def assess(self, reading: dict | None) -> dict:
        reading = reading or {}
        status = reading.get("status", "unknown")
        window = reading.get("window") or {}
        hours = reading.get("hours_to_limit_pessimistic", reading.get("hours_to_limit"))
        urgency = self.URGENCY.get(status, "unknown")
        if urgency == "act_now" and window.get("status") == "closed":
            urgency = "too_late_to_act"
        return {
            "available": status not in ("unknown",),
            "status": status, "urgency": urgency,
            "hours_to_limit": reading.get("hours_to_limit"),
            "hours_to_limit_pessimistic": hours,
            "current_batch_sulfur": reading.get("current_batch_sulfur"),
            "slope_ppm_per_hour": reading.get("slope_ppm_per_hour"),
            "window_closes_in_hours": window.get("closes_in_hours"),
            "reason": reading.get("reason", "Оценка запаса не выполнялась"),
            "scope": "Запас считается по скользящему среднему ПАК как прокси партии; "
                     "это не сертифицированный показатель товарной партии.",
        }


class OptimizerAgent:
    def propose(self, cfg: dict, reduce_throughput=False) -> list[dict]:
        fractions = sorted({cfg["current_reserve_fraction"], *[i / 100 for i in range(0, 101, 5)]})
        if reduce_throughput:
            flows = [cfg["current_throughput_tph"] - i * 10 for i in range(1, 11)
                     if cfg["current_throughput_tph"] - i * 10 >= cfg["min_throughput_tph"]]
        else:
            flows = [cfg["current_throughput_tph"]]
        return [{"reserve_fraction": f, "main_fraction": 1 - f, "throughput_tph": q,
                 "unit_cost_proxy": 1 + f * (cfg["reserve_cost_multiplier"] - 1),
                 "energy_proxy": (q / cfg["max_throughput_tph"]) ** 2}
                for q in flows for f in fractions]

    @staticmethod
    def pareto(candidates: list[dict]) -> list[dict]:
        def objectives(c):
            return (-c["throughput_tph"], c["unit_cost_proxy"], c["energy_proxy"], c["reliability"]["pump_load"])
        return [c for c in candidates if not any(
            all(a <= b for a, b in zip(objectives(other), objectives(c))) and
            any(a < b for a, b in zip(objectives(other), objectives(c))) for other in candidates)]


def validate_scenario(cfg):
    if cfg.get("kind") != "synthetic_blending_scenario":
        raise ValueError("Не подтвержден демонстрационный характер смешения")
    keys = ("sulfur_limit", "reserve_sulfur_lower", "reserve_sulfur_upper", "current_reserve_fraction",
            "current_throughput_tph", "min_throughput_tph", "max_throughput_tph", "reserve_available_tph",
            "reserve_pump_limit_tph", "max_reserve_fraction", "max_fraction_step", "reserve_cost_multiplier")
    if any(not isinstance(cfg.get(k), (int, float)) or not math.isfinite(cfg[k]) or cfg[k] < 0 for k in keys):
        raise ValueError("Параметры сценария должны быть конечными неотрицательными числами")
    if not (0 < cfg["min_throughput_tph"] <= cfg["current_throughput_tph"] <= cfg["max_throughput_tph"] and
            0 <= cfg["current_reserve_fraction"] <= cfg["max_reserve_fraction"] <= 1 and
            cfg["reserve_sulfur_lower"] <= cfg["reserve_sulfur_upper"] and cfg["reserve_pump_limit_tph"] > 0 and
            cfg["max_fraction_step"] <= 1):
        raise ValueError("Несогласованные диапазоны сценария")


class Coordinator:
    def __init__(self, cfg):
        validate_scenario(cfg)
        self.cfg = cfg
        self.data = DataAgent()
        self.quality = QualityAgent()
        self.reliability = ReliabilityAgent()
        self.optimizer = OptimizerAgent()
        self.margin = MarginAgent()

    def run(self, state: dict, forecast: Forecast, fallback: Forecast | None = None,
            risk: dict | None = None, evidence: dict | None = None) -> dict:
        cfg = self.cfg
        evidence = evidence or {}
        ledger = Ledger()
        trust = self.data.assess(state)
        trace = [{"agent": "data", "result": trust}]
        self._state_claims(ledger, state, trust)
        risk_reading = (risk or {}).get("fallback" if trust["fallback"] else "main") if trust["usable"] else None
        risk_assessment = self.quality.assess_risk(risk_reading)
        if risk is not None:
            trace.append({"agent": "quality", "event": "Независимая проверка риска превышения", "result": risk_assessment})
            if risk_assessment["available"]:
                ledger.say("quality", f"Оценка риска превышения {risk_assessment['score']:.3g} при пороге "
                                      f"{risk_assessment['threshold']:.3g}: тревога "
                                      f"{'поднята' if risk_assessment['alarm'] else 'не поднята'}",
                           [model_result(risk_assessment["model"], "score", risk_assessment["score"]),
                            model_result(risk_assessment["model"], "threshold", risk_assessment["threshold"],
                                         "порог заморожен на периоде калибровки")])
        margin_assessment = self.margin.assess(evidence.get("margin"))
        if evidence.get("margin"):
            trace.append({"agent": "margin", "event": "Запас партии до предела", "result": margin_assessment})
            self._margin_claims(ledger, margin_assessment, evidence["margin"])
        chain = evidence.get("attribution") or {}
        if chain.get("available"):
            trace.append({"agent": "chain", "event": "Разбор вклада участков цепочки",
                          "leading": chain.get("leading_group")})
            ledger.say("chain", chain["reason"],
                       [model_result(str(chain.get("model", "forecast")), "prediction", chain.get("prediction"),
                                     "замена группы признаков на медиану обучающего периода")])
        cases = evidence.get("twins") or {}
        if cases.get("usable"):
            trace.append({"agent": "cases", "event": "Похожие ситуации в истории", "twins": cases.get("twins")})
            ledger.say("cases", cases["reason"],
                       [measurement("история", date, None, "похожая ситуация, проверяемая по этой дате")
                        for date in cases.get("dates", [])[:5]])
        control = evidence.get("control_review") or {}
        if control:
            trace.append({"agent": "support", "event": "Проверка права советовать по управляющему тегу",
                          "tag": control.get("tag"), "allowed": control.get("allowed")})
            self._control_claims(ledger, control)
        # Never pass a forecast requiring the rejected analyzer through unchanged.
        if trust["fallback"]:
            forecast = fallback or Forecast(None, None, None, "unavailable")
            trace.append({"agent": "quality", "event": "ПАК исключен; запрошен отдельный резервный прогноз"})
        result = {"scope": cfg["kind"], "commercial_release_allowed": False,
                  "state": state, "forecast": asdict(forecast), "scenario": cfg,
                  "risk": risk_assessment, "margin": margin_assessment,
                  "chain_attribution": chain or None, "similar_cases": cases or None,
                  "control_review": control or None,
                  "trust": trust, "trace": trace, "candidates": [], "alternatives": [], "chosen": None}

        def finish(status, reason):
            result.update(status=status, reason=reason)
            trace.append({"agent": "coordinator", "status": status, "reason": reason})
            ledger.say("coordinator", f"Итог: {status}. {reason}",
                       [scenario_input("kind", None, cfg["kind"]),
                        scenario_input("sulfur_limit", cfg["sulfur_limit"], "жесткое ограничение сценария")])
            result["claims"] = ledger.to_dict()
            content = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
            result["decision_id"] = hashlib.sha256(content.encode()).hexdigest()[:16]
            return result

        if not trust["usable"] or not self.quality.valid_forecast(forecast):
            return finish("refuse", "Недостаточно достоверных данных или нет допустимого прогноза")
        trace.append({"agent": "quality", "upper": forecast.upper, "limit": cfg["sulfur_limit"],
                      "model": forecast.model})
        ledger.say("quality", f"Верхняя оценка серы после гидроочистки {forecast.upper:.2f} мг/кг "
                              f"при пределе {cfg['sulfur_limit']:g}",
                   [model_result(forecast.model, "верхняя граница диапазона", forecast.upper),
                    model_result(forecast.model, "точечный прогноз", forecast.value),
                    scenario_input("sulfur_limit", cfg["sulfur_limit"])])

        def assess(candidate):
            c = dict(candidate)
            f, q = c["reserve_fraction"], c["throughput_tph"]
            c["quality"] = self.quality.assess(forecast, f, cfg)
            c["reliability"] = self.reliability.assess(f, q, cfg)
            c["allowed"] = c["quality"]["allowed"] and c["reliability"]["allowed"]
            c["reasons"] = c["reliability"]["reasons"] + ([] if c["quality"]["allowed"] else ["Верхняя оценка серы выше предела"])
            result["candidates"].append(c)
            return c

        current = assess(next(c for c in self.optimizer.propose(cfg)
                              if c["reserve_fraction"] == cfg["current_reserve_fraction"]))
        if current["allowed"]:
            result["chosen"] = current
            ledger.say("optimizer", f"Текущий режим проходит проверки: верхняя оценка серы смеси "
                                    f"{current['quality']['sulfur_upper']:.2f} мг/кг, запас "
                                    f"{current['quality']['margin']:.2f} мг/кг",
                       [model_result(forecast.model, "верхняя граница диапазона", forecast.upper),
                        scenario_input("current_reserve_fraction", cfg["current_reserve_fraction"]),
                        scenario_input("sulfur_limit", cfg["sulfur_limit"])])
            return finish("hold", "Текущий режим проходит ограничения сценария; изменения не нужны")

        for round_number in (1, 2):
            candidates = self.optimizer.propose(cfg, reduce_throughput=round_number == 2)
            checked = [assess(c) for c in candidates]
            safe = [c for c in checked if c["allowed"]]
            trace.append({"agent": "optimizer", "round": round_number, "proposed": len(checked), "allowed": len(safe)})
            vetoes = sum(c["quality"]["allowed"] and not c["reliability"]["allowed"] for c in checked)
            trace.append({"agent": "reliability", "round": round_number, "vetoed_quality_feasible": vetoes})
            if vetoes:
                ledger.say("reliability", f"Запрещено {vetoes} вариантов, проходивших по качеству, "
                                          f"из-за ограничений оборудования сценария",
                           [scenario_input("reserve_pump_limit_tph", cfg["reserve_pump_limit_tph"]),
                            scenario_input("reserve_available_tph", cfg["reserve_available_tph"])])
            if safe:
                frontier = self.optimizer.pareto(safe)
                result["alternatives"] = frontier
                chosen = min(frontier, key=lambda c: (-c["throughput_tph"], c["unit_cost_proxy"], c["reliability"]["pump_load"]))
                result["chosen"] = chosen
                ledger.say("optimizer", f"Выбран вариант: доля резерва {chosen['reserve_fraction']:.0%}, "
                                        f"расход {chosen['throughput_tph']:g} т/ч, верхняя оценка серы смеси "
                                        f"{chosen['quality']['sulfur_upper']:.2f} мг/кг",
                           [model_result(forecast.model, "верхняя граница диапазона", forecast.upper),
                            scenario_input("reserve_sulfur_upper", cfg["reserve_sulfur_upper"]),
                            scenario_input("max_fraction_step", cfg["max_fraction_step"]),
                            scenario_input("frontier", len(frontier), "число вариантов на фронте Парето")])
                return finish("recommend_scenario", "Допустимый вариант сценария: максимальный выпуск, затем меньшая условная стоимость")
            if round_number == 1:
                trace.append({"agent": "coordinator", "event": "Нет допустимых вариантов при текущем выпуске; запрос пересчета с меньшим расходом"})
        return finish("refuse", "Ни один вариант не проходит одновременно ограничения качества и оборудования")

    @staticmethod
    def _state_claims(ledger: Ledger, state: dict, trust: dict):
        if state.get("lab_value") is not None:
            ledger.say("data", f"Последний лабораторный результат {state['lab_value']:.2f} мг/кг, "
                               f"возраст {state.get('lab_age_hours') or 0:.1f} ч",
                       [measurement("ЛИМС Mg.Sulfur", state.get("lab_sample_time"), state.get("lab_value"))])
        if state.get("pak_value") is not None:
            ledger.say("data", f"Поточный анализатор {state['pak_value']:.2f} мг/кг, "
                               f"возраст {state.get('pak_age_minutes') or 0:.0f} мин",
                       [measurement("ПАК 24-2000:Mg.Sulfur", state.get("pak_sample_time"), state.get("pak_value"))])
        for reason in trust.get("reasons", []):
            ledger.say("data", reason,
                       [measurement("состояние источников", state.get("decision_time"), None,
                                    "проверка доступности и согласованности источников качества")])

    @staticmethod
    def _margin_claims(ledger: Ledger, assessment: dict, reading: dict):
        hours = assessment.get("hours_to_limit_pessimistic")
        if assessment.get("status") == "approaching" and hours is not None:
            ledger.say("margin", f"Скользящее среднее {assessment['current_batch_sulfur']:.2f} мг/кг растет на "
                                 f"{assessment['slope_ppm_per_hour']:.3f} мг/кг в час; до предела около "
                                 f"{hours:.1f} ч по осторожной оценке",
                       [measurement("ПАК, скользящее среднее", reading.get("at"),
                                    assessment.get("current_batch_sulfur"),
                                    f"окно {reading.get('batch_window_hours')} ч"),
                        model_result("линейный тренд", "наклон", assessment.get("slope_ppm_per_hour"),
                                     f"разброс вокруг тренда {reading.get('residual_ppm', 0):.2f} мг/кг")])
        else:
            ledger.say("margin", assessment.get("reason", "Оценка запаса недоступна"),
                       [measurement("ПАК, скользящее среднее", reading.get("at"),
                                    assessment.get("current_batch_sulfur"),
                                    f"точек в окне: {reading.get('points')}")])
        if assessment.get("window_closes_in_hours") is not None:
            ledger.say("margin", f"Окно для действия закрывается через "
                                 f"{assessment['window_closes_in_hours']:.1f} ч с учетом запаздывания отклика",
                       [model_result("карта запаздывания", "принятое запаздывание отклика",
                                     (reading.get("window") or {}).get("response_lag_hours"))])

    @staticmethod
    def _control_claims(ledger: Ledger, control: dict):
        tag = control.get("tag", "тег")
        if control.get("allowed"):
            experiments = control.get("natural_experiments", {})
            ledger.say("support", f"История позволяет обсуждать управление тегом {tag}",
                       [measurement(tag, experiments.get("last"), None,
                                    f"естественных окон: {experiments.get('windows')}")])
            return
        for reason in control.get("blocking", []):
            ledger.say("support", f"{tag}: {reason}",
                       [measurement(tag, control.get("natural_experiments", {}).get("last"), None,
                                    "проверка права советовать по этому тегу")])
