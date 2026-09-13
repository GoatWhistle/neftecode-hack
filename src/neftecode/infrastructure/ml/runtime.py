"""Run the trained advisor at a requested historical forecast origin."""
from collections.abc import Callable

import numpy as np
import pandas as pd

from neftecode.infrastructure.ml import attribution, twins as twins_module
from neftecode.infrastructure.ml.agents import Coordinator, DataAgent, Forecast
from neftecode.infrastructure.data.data import build_features
from neftecode.infrastructure.ml.forecast import interval, predict_candidate
from neftecode.infrastructure.ml.risk import score_candidate
from neftecode.infrastructure.ml.support import SupportAgent


def validate_origin(at, bundle):
    when = pd.Timestamp(at)
    if pd.isna(when) or when.tzinfo is not None:
        raise ValueError("Укажите корректное местное время без часового пояса, как в исходных данных")
    if when < pd.Timestamp(bundle["config"]["calibration_end"]):
        raise ValueError("На этот момент модель и калибровка еще не были доступны; запуск создал бы утечку из будущего")
    return when


def gather_evidence(signals, online, bundle, when, x, predict,
                    margin_evaluator: Callable | None = None) -> dict:
    """Margin, chain attribution, historical twins and the right to advise on a control tag.

    Everything here reads only data available at `when`; a failure in one block
    removes that block instead of stopping the decision.
    """
    cfg = bundle["config"]
    evidence: dict = {}

    def missing(*keys):
        """An artifact trained by an older config must not be patched with silent defaults."""
        absent = [k for k in keys if k not in cfg]
        return ("Блок отключен: в конфигурации обученной модели нет параметров "
                + ", ".join(absent)) if absent else None

    past = online.loc[online.time <= when]
    gap = missing("sulfur_limit", "margin_trend_window_hours", "batch_window_hours",
                  "margin_max_horizon_hours", "response_lag_hours")
    if gap:
        evidence["margin"] = {"status": "unknown", "reason": gap}
    elif len(past) > 1:
        if margin_evaluator is None:
            evidence["margin"] = {
                "status": "unknown",
                "reason": "Блок отключен: расчёт запаса не подключён в composition root",
            }
        else:
            evidence["margin"] = margin_evaluator(past, when, cfg)

    reference = bundle.get("reference_row")
    if reference is not None:
        chain = attribution.attribute_decision(predict, x, reference)
        chain["model"] = bundle["selected"]
        evidence["attribution"] = chain

    history = signals.loc[signals.index < when]
    target = pd.Series(online.value.to_numpy(float), index=pd.DatetimeIndex(online.time))
    past_target = target.loc[target.index < when]
    context = [c for c in history.columns if c.startswith("ht.")]
    current = history.iloc[-1].to_dict() if len(history) else {}
    gap = missing("twins_k", "twins_min_separation_hours", "twins_horizon_hours", "sulfur_limit")
    if gap:
        evidence["twins"] = {"usable": False, "reason": gap}
    else:
        try:
            found = twins_module.find_twins(history, current, context, k=cfg["twins_k"], before=when,
                                            reference_time=when,
                                            min_separation_hours=cfg["twins_min_separation_hours"])
            outcomes = twins_module.outcomes(found, past_target, cfg["twins_horizon_hours"])
            evidence["twins"] = twins_module.summarise(outcomes, cfg["sulfur_limit"])
        except ValueError as exc:
            evidence["twins"] = {"usable": False, "reason": str(exc)}

    candidates = [t for t in cfg.get("control_candidates", []) if t in history.columns]
    if candidates and len(history) > 1000:
        agent = SupportAgent(history, past_target, context)
        tag = candidates[0]
        proposed = float(history[tag].iloc[-1])
        step = float(history[tag].diff().std())
        try:
            evidence["control_review"] = agent.review(
                tag, current, proposed + (3 * step if np.isfinite(step) else 0.0))
        except ValueError as exc:
            evidence["control_review"] = {"tag": tag, "allowed": False, "blocking": [str(exc)]}
    return evidence


def decision_at(signals, lab, online, bundle, at, scenario, with_evidence: bool = True,
                margin_evaluator: Callable | None = None):
    when = validate_origin(at, bundle)
    cfg = bundle["config"]
    x, metadata = build_features(signals, lab, online, [when], cfg)
    state = {}
    for key, value in metadata.iloc[0].items():
        if pd.isna(value):
            state[key] = None
        elif isinstance(value, pd.Timestamp):
            state[key] = value.isoformat()
        elif isinstance(value, np.generic):
            state[key] = value.item()
        else:
            state[key] = value
    state.update(origin="historical_query_with_synthetic_blending",
                 forecast_for=(when + pd.Timedelta(hours=cfg["horizon_hours"])).isoformat())
    coordinator = Coordinator(scenario)
    if not DataAgent().assess(state)["usable"]:
        return coordinator.run(state, Forecast(None, None, None, "unavailable"))

    def forecast(name):
        value = predict_candidate(bundle, name, x)[0]
        lower, upper = interval(value, bundle["radii"][name])
        return Forecast(float(value), float(lower), float(upper), name)

    risk_bundle = bundle.get("risk")
    risk = None
    if risk_bundle:
        risk = {}
        for role, key in [("main", "selected"), ("fallback", "fallback")]:
            name = risk_bundle[key]
            score = float(score_candidate(risk_bundle, name, x)[0])
            risk[role] = {"score": score if np.isfinite(score) else None,
                          "threshold": risk_bundle["thresholds"][name], "model": name}
    evidence = {}
    if with_evidence:
        evidence = gather_evidence(
            signals, online, bundle, when, x,
            lambda frame: predict_candidate(bundle, bundle["selected"], frame),
            margin_evaluator,
        )
    return coordinator.run(state, forecast(bundle["selected"]), forecast(bundle["fallback"]), risk, evidence)
