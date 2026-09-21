from functools import partial
import json
from pathlib import Path

from neftecode.application.services.explain import explain
from neftecode.composition.decision import run_demo_decision
from neftecode.domain.production.inventory import initial_state
from neftecode.application.services.robustness import RobustnessCheck
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.agentic import default_decision_factory
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.advisor import load_response_model
from neftecode.infrastructure.live.snapshots import load_snapshots
from neftecode.presentation.demo import Demo, scenes as demo_scenes
from neftecode.presentation.web.ui import Screen, error_payload

def screen(args, parser, root, out):
    target = out / "screen.json"
    try:
        scenario_path = args.scenario or (root / "config/scenarios/sour_crude.json")
        scenario = load_scenario(scenario_path)
        if args.decision:
            decision = json.loads(args.decision.read_text(encoding="utf-8"))
        else:
            raw_scenario = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
            decision = default_decision_factory(root)(scenario, RobustnessCheck(
                scenario, raw_scenario, scenario_parser=parse_scenario
            )).decide(budget=DEFAULT_BUDGET, raw_scenario=raw_scenario)
            write_json(out / f"decision-{scenario.scenario_id}.json", decision)
        payload = Screen(
            decision, explain(decision, scenario),
            inventories={k: v.inventory_t for k, v in initial_state(scenario).items()},
            state_origin="сценарные условия",
        ).payload()
    except (ValueError, OSError) as exc:
        payload = error_payload(str(exc))
    write_json(target, payload)
    print(f"Экран оператора: {target}")

def scenes(args, parser, root, out):
    scenario_path = args.scenario or (root / "config/scenarios/baseline.json")
    trust_cfg, trust_origin = load_trust_rules(root, out)
    snapshots = load_snapshots(out)
    runner = partial(run_demo_decision, decision_factory=default_decision_factory(root))
    demo = Demo.from_path(scenario_path, runner, trust_cfg, budget=DEFAULT_BUDGET, trust_origin=trust_origin,
                          snapshots=snapshots, response_model=load_response_model(root, out))
    folder = out / "scenes"
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for number, scene in enumerate(demo_scenes(scenario_path, snapshots), start=1):
        result = demo.run(scene["changes"], scene["fault"], snapshot=scene.get("snapshot"))
        page = folder / f"{number:02d}-{scene['name'].replace(' ', '_')}.json"
        write_json(page, result["screen"])
        status = "отклонено" if result["rejected"] else result["decision"]["status"]
        index.append({"scene": scene["name"], "expected": scene["expect"],
                      "status": status, "injected_fault": scene["fault"],
                      "snapshot": result.get("snapshot"), "state_origin": result.get("state_origin"),
                      "page": str(page.relative_to(out)), "screen": result["screen"]})
        print(f"  {scene['name']:48s} {status:20s} {result.get('snapshot') or 'синтетика'}")
    quality_risk_built = any(s["scene"].startswith("Риск ухудшения качества") for s in index)
    warnings = []
    if not snapshots:
        warnings.append(f"СРЕЗОВ НЕТ: каталог {out / 'snapshots'} пуст, реальных измерений 2026 года "
                        f"в демонстрации нет ни в одной сцене. Все состояния синтетические. "
                        f"Срезы строит 'uv run neftecode snapshot --all' по выданным данным в task/.")
    if not quality_risk_built:
        warnings.append("Сцена «Риск ухудшения качества» НЕ построена: она существует только на реальном срезе "
                        "24.07.2026, инъекции риска качества здесь нет и быть не должно. "
                        "Обязательный пункт раздела 6 ТЗ «период с риском ухудшения качества» не покрыт.")
    write_json(out / "scenes.json", {
        "scenario": str(scenario_path), "scenes": index, "trust_origin": trust_origin,
        "snapshots": [item["at"] for item in snapshots],
        "snapshots_available": bool(snapshots),
        "quality_risk_scene_built": quality_risk_built,
        "warnings": warnings,
        "note": "Каждая сцена получена пересчётом через тот же загрузчик и то же ядро. Сцены со срезом идут на "
                "реальных измерениях 2026 года; без срезов состояние синтетическое. Инъекции отказов помечены как модельные."})
    for warning in warnings:
        print()
        print(f"ВНИМАНИЕ. {warning}")
    print(f"Журнал: {out / 'scenes.json'}")
