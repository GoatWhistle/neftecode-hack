import json

from neftecode.application.agentic.contracts import AgentSettings
from neftecode.application.agentic.decision import AgenticMakeDecision
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.evaluation.robustness import RobustnessCheck
from neftecode.domain.advisory.optimizer import DEFAULT_BUDGET
from neftecode.infrastructure.artifacts import write_json
from neftecode.infrastructure.config.scenario import parse_scenario
from neftecode.infrastructure.llm.demo_policy import demo_llm
from neftecode.infrastructure.response.unavailable import UnavailableResponseEffect
from neftecode.presentation.reports.agent_trace import render_agent_trace

SCENARIOS = ("baseline", "sour_crude", "ample_reserve", "no_feasible")
LABEL = ("Детерминированная демонстрация: агентами управляет заранее написанная политика (provider=scripted), "
         "а не языковая модель. Показывает механику слоя: выбор инструментов по результатам, ограничения, "
         "разрешение кодом, Gate и fallback.")


def agent_demo(args, parser, root, out):
    records, lines = [], [f"# Агентный режим: детерминированная демонстрация\n\n{LABEL}\n"]
    names = [args.scenario.stem] if args.scenario else list(SCENARIOS)
    for name in names:
        path = args.scenario if args.scenario else root / "config/scenarios" / f"{name}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        scenario = parse_scenario(document)
        robustness = RobustnessCheck(scenario, document, scenario_parser=parse_scenario)
        legacy = MakeDecision(scenario, robustness_evaluator=robustness).decide(budget=DEFAULT_BUDGET, raw_scenario=document)
        agentic = AgenticMakeDecision(scenario, demo_llm(), settings=AgentSettings(), robustness_evaluator=robustness,
                                      response_effect=UnavailableResponseEffect()).decide(budget=DEFAULT_BUDGET, raw_scenario=document)
        trace = render_agent_trace(agentic)
        records.append({"scenario": scenario.scenario_id,
                        "legacy": {"status": legacy["status"], "plan": (legacy["selected_plan"] or {}).get("plan_id"),
                                   "decision_id": legacy["decision_id"]},
                        "agentic": {"status": agentic["status"], "plan": (agentic["selected_plan"] or {}).get("plan_id"),
                                    "decision_id": agentic["decision_id"], **agentic["agentic"]},
                        "rendered": trace})
        lines.append(f"## {scenario.scenario_id}\n\n```text\n" + "\n".join(trace) + "\n```\n")
        print(f"  {scenario.scenario_id:16s} legacy {legacy['status']:18s} agentic {agentic['status']:18s} "
              f"{agentic['agentic']['outcome']}")
    write_json(out / "agent-demo.json", {"label": LABEL, "scenarios": records})
    (out / "agent-demo.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Журнал: {out / 'agent-demo.json'}\nОтчёт: {out / 'agent-demo.md'}")
