"""CLI handlers for screens."""
import json
from pathlib import Path

from neftecode.application.services.explain import explain
from neftecode.composition.decision import run_demo_decision
from neftecode.domain.production.inventory import initial_state
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.presentation.demo import Demo, scenes as demo_scenes
from neftecode.presentation.web.ui import Screen, error_payload, write_screen

def screen(args, parser, root, out):
    target = out / "screen.html"
    try:
        scenario_path = args.scenario or (root / "config/scenarios/sour_crude.json")
        scenario = load_scenario(scenario_path)
        if args.decision:
            # Reviewing a stored decision: nothing is recomputed.
            decision = json.loads(args.decision.read_text())
        else:
            raw_scenario = json.loads(Path(scenario_path).read_text())
            decision = default_decision_factory()(scenario, RobustnessCheck(
                scenario, raw_scenario, scenario_parser=parse_scenario
            )).decide(budget=400, raw_scenario=raw_scenario)
            write_json(out / f"decision-{scenario.scenario_id}.json", decision)
        payload = Screen(
            decision, explain(decision, scenario),
            inventories={k: v.inventory_t for k, v in initial_state(scenario).items()},
        ).payload()
    except (ValueError, OSError) as exc:
        payload = error_payload(str(exc))
    write_screen(target, payload)
    print(f"Экран оператора: {target}")

def scenes(args, parser, root, out):
    scenario_path = args.scenario or (root / "config/scenarios/baseline.json")
    trust_cfg, trust_origin = load_trust_rules(root, out)
    demo = Demo.from_path(scenario_path, run_demo_decision, trust_cfg, budget=400, trust_origin=trust_origin)
    folder = out / "scenes"
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for number, scene in enumerate(demo_scenes(scenario_path), start=1):
        result = demo.run(scene["changes"], scene["fault"])
        page = folder / f"{number:02d}-{scene['name'].replace(' ', '_')}.html"
        write_screen(page, result["screen"])
        status = "отклонено" if result["rejected"] else result["decision"]["status"]
        index.append({"scene": scene["name"], "expected": scene["expect"],
                      "status": status, "injected_fault": scene["fault"],
                      "page": str(page.relative_to(out))})
        print(f"  {scene['name']:48s} {status}")
    write_json(out / "scenes.json", {
        "scenario": str(scenario_path), "scenes": index, "trust_origin": trust_origin,
        "note": "Каждая сцена получена пересчётом через тот же загрузчик и то же ядро. "
                "Инъекции отказов помечены как модельные."})
    print(f"Журнал: {out / 'scenes.json'}")
