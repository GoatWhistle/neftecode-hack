"""CLI handlers for live."""
import json
from pathlib import Path
import pickle

from neftecode.domain.production.inventory import initial_state
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.data.data import load_sources
from neftecode.infrastructure.live.advisor import LiveAdviceAdapter, bind_forecast
from neftecode.infrastructure.live.origin import validate_origin
from neftecode.presentation.web.ui import Screen, error_payload, write_screen

def handle(args, parser, root, out):
    if not args.at:
        parser.error("Для advise нужен --at с местным временем решения")
    with (out / "model.pkl").open("rb") as stream:
        bundle = pickle.load(stream)
    when = validate_origin(args.at, bundle)
    signals, lab, online = load_sources(root / "task")
    scenario_path = args.scenario or (root / "config/scenarios/baseline.json")
    raw_scenario = json.loads(Path(scenario_path).read_text())
    advisor = LiveAdviceAdapter(signals, lab, online, bundle,
                          raw_scenario,
                          robustness_evaluator=RobustnessCheck(
                              parse_scenario(raw_scenario), raw_scenario,
                              scenario_parser=parse_scenario))
    result = advisor.advise(args.at)
    stamp = when.strftime("%Y%m%d-%H%M%S")
    path = out / f"decision-{stamp}.json"
    write_json(path, result)
    if result.get("decision") is None:
        screen_payload = error_payload(result.get("error", "Решение не получено"))
    else:
        raw_for_screen = (advisor.raw_scenario
                           if not result["forecast"].get("available")
                           else advisor.raw_scenario.copy())
        if result["forecast"].get("available") and result["trust"].get("usable"):
            raw_for_screen = bind_forecast(advisor.raw_scenario, result["forecast"], state=result["state"])
        scenario_for_screen = parse_scenario(raw_for_screen)
        screen_payload = Screen(
            result["decision"], result["explanation"],
            inventories={k: v.inventory_t for k, v in initial_state(scenario_for_screen).items()},
            sources=list(result["trust"].get("sources", {}).values()),
        ).payload()
    write_screen(out / f"screen-{stamp}.html", screen_payload)
    forecast = result["forecast"]
    print((f"Прогноз {forecast['model']}: {forecast['value']:.2f} мг/кг, "
           f"верхняя граница {forecast['upper']:.2f}") if forecast["available"]
          else forecast.get("reason", "Прогноз недоступен"))
    print(f"Источники: {result['trust']['primary'] or 'нет пригодного'}")
    if result["decision"] is None:
        print(f"Решение не выдано: {result.get('error')}")
    else:
        print(f"{result['decision']['status']}: {result['decision']['reason']}")
    print(f"Журнал: {path}\nЭкран: {out / f'screen-{stamp}.html'}")
