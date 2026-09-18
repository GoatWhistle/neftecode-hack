"""CLI handlers for live."""
import json
from pathlib import Path
import pickle

from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.data.data import load_sources
from neftecode.infrastructure.live.advisor import LiveAdviceAdapter, interval_coverage, load_response_model
from neftecode.infrastructure.live.origin import validate_origin
from neftecode.infrastructure.live.snapshots import build_snapshot, write_snapshot
from neftecode.presentation.web.ui import Screen, error_payload, write_screen

def handle(args, parser, root, out):
    if not args.at:
        parser.error("Для advise нужен --at с местным временем решения")
    with (out / "model.pkl").open("rb") as stream:
        bundle = pickle.load(stream)
    when = validate_origin(args.at, bundle)
    signals, lab, online = load_sources(root / "task", bundle["config"]["train_end"])
    scenario_path = args.scenario or (root / "config/scenarios/baseline.json")
    raw_scenario = json.loads(Path(scenario_path).read_text())
    # Устойчивость проверяется на связанном сценарии (после прогноза и измерений), а не на исходном.
    advisor = LiveAdviceAdapter(signals, lab, online, bundle,
                          raw_scenario,
                          robustness_factory=lambda scenario, raw: RobustnessCheck(
                              scenario, raw, scenario_parser=parse_scenario),
                          decision_factory=default_decision_factory(),
                          response_model=load_response_model(root, out),
                          coverage={name: interval_coverage(out, bundle, name)
                                    for name in bundle.get("radii", {})})
    result = advisor.advise(args.at)
    stamp = when.strftime("%Y%m%d-%H%M%S")
    path = out / f"decision-{stamp}.json"
    write_json(path, result)
    if result.get("decision") is None:
        screen_payload = error_payload(result.get("error", "Решение не получено"))
    else:
        bound = bool(result["trust"].get("usable") and result["forecast"].get("available"))
        screen_payload = Screen(
            result["decision"], result["explanation"],
            inventories=result.get("inventories") or {},
            sources=list(result["trust"].get("sources", {}).values()),
            # Пороги доверия здесь берутся из обученной модели, состояние — реальные измерения.
            rule_origin="derived:artifacts/model.pkl",
            state_origin=(f"реальные измерения на момент решения: {when:%d.%m.%Y %H:%M}" if bound else
                          f"реальный срез {when:%d.%m.%Y %H:%M} без привязки: измерения показаны, "
                          "сценарные уставки не используются"),
            decision_time=(result.get("state") or {}).get("decision_time") or result.get("at"),
            forecast=result.get("forecast"),
            forecast_used=bound,
        ).payload()
    write_screen(out / f"screen-{stamp}.html", screen_payload)
    forecast = result["forecast"]
    print((f"Прогноз {forecast['model']}: {forecast['value']:.2f} мг/кг, "
           f"верхняя граница {forecast['upper']:.2f}") if forecast["available"]
          else forecast.get("reason", "Прогноз недоступен"))
    print(f"Источники: {result['trust']['primary'] or 'нет пригодного'}")
    for warning in ((result.get("binding") or {}).get("measurement_binding") or {}).get("warnings") or ():
        print(f"Внимание: {warning}")
    if result["decision"] is None:
        print(f"Решение не выдано: {result.get('error')}")
    else:
        print(f"{result['decision']['status']}: {result['decision']['reason']}")
    print(f"Журнал: {path}\nЭкран: {out / f'screen-{stamp}.html'}")


def snapshot(args, parser, root, out):
    """Заморозить реальные срезы для демонстрации без task/."""
    if not args.at and not args.all:
        parser.error("Для snapshot нужен --at или --all")
    with (out / "model.pkl").open("rb") as stream:
        bundle = pickle.load(stream)
    moments = []
    if args.all:
        moments = json.loads((root / "config/snapshot_moments.json").read_text(encoding="utf-8"))
    if args.at:
        moments.append({"at": args.at, "label": "", "why": ""})
    signals, lab, online = load_sources(root / "task", bundle["config"]["train_end"])
    rules_path = out / "source_rules.json"
    rules_fp = None
    if rules_path.exists():
        rules_fp = json.loads(rules_path.read_text(encoding="utf-8")).get("model_fingerprint")
    coverage = {name: interval_coverage(out, bundle, name)
                for name in bundle.get("radii", {})}
    for moment in moments:
        snap = build_snapshot(signals, lab, online, bundle, moment["at"], moment.get("label", ""),
                              moment.get("why", ""), tuple(moment.get("synthetic_missing") or ()),
                              coverage=coverage, source_rules_fingerprint=rules_fp)
        path = write_snapshot(out, snap)
        print(f"  {snap['at']}  {snap['label'] or '-':40s} {snap['trust']['primary'] or 'нет источника':6s} {path.name}")
