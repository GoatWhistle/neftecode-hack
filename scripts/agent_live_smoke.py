"""One minimal live check of the agent layer against a real provider.

Default mode is a dry run: it loads the configuration, prints it without the key and touches no network.
`--live` performs exactly one end-to-end decision. Rerunning it is a deliberate act: quota is limited and
the Z.AI Coding Plan terms restrict where its key may be used (see plan/07-risks.md, R10).

    uv run python scripts/agent_live_smoke.py                 # dry run
    uv run python scripts/agent_live_smoke.py --live          # one real decision
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neftecode.application.agentic.decision import AgenticMakeDecision  # noqa: E402
from neftecode.evaluation.robustness import RobustnessCheck  # noqa: E402
from neftecode.infrastructure.agentic.factory import build_decision_factory  # noqa: E402
from neftecode.infrastructure.config.scenario import parse_scenario  # noqa: E402
from neftecode.presentation.reports.agent_trace import render_agent_trace  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Одна живая проверка агентного режима")
    parser.add_argument("--live", action="store_true", help="выполнить один реальный запрос к провайдеру")
    parser.add_argument("--scenario", default="baseline")
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "agent-live-smoke.json")
    args = parser.parse_args(argv)

    environ = dict(os.environ)
    environ.pop("PYTEST_CURRENT_TEST", None)
    environ["AGENTIC_DECISION_ENABLED"] = "1"
    environ.setdefault("LLM_MAX_RETRIES", "0")
    environ["AGENT_MAX_LLM_CALLS"] = str(args.max_calls)
    factory = build_decision_factory(environ, dotenv_path=ROOT / ".env")
    description = factory.describe()
    print("Конфигурация (без ключа):")
    print(json.dumps({k: description[k] for k in ("provider", "model", "base_url", "api_key", "agentic_enabled",
                                                  "configuration_error") if k in description},
                     ensure_ascii=False, indent=2))
    print(f"scenario={args.scenario}  budget={args.budget}  max_llm_calls={args.max_calls}  "
          f"max_steps={factory.settings.max_steps}  timeout_s={factory.settings.timeout_s}")
    if factory.configuration_error:
        print(f"Конфигурация не готова: {factory.configuration_error}")
        return 2
    if not args.live:
        print("Сухой прогон: сеть не использовалась. Для одного реального запроса добавьте --live.")
        return 0

    document = json.loads((ROOT / "config/scenarios" / f"{args.scenario}.json").read_text())
    scenario = parse_scenario(document)
    maker = factory(scenario, RobustnessCheck(scenario, document, scenario_parser=parse_scenario))
    if not isinstance(maker, AgenticMakeDecision):
        print("Агентный режим не собран: проверьте AGENTIC_DECISION_ENABLED и настройки провайдера")
        return 2
    decision = maker.decide(budget=args.budget, raw_scenario=document)
    info = decision["agentic"]
    print("\n".join(render_agent_trace(decision)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"configuration": description, "status": decision["status"],
                                    "plan": (decision["selected_plan"] or {}).get("plan_id"),
                                    "decision_id": decision["decision_id"], "agentic": info,
                                    "rendered": render_agent_trace(decision)},
                                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Журнал: {args.out}")
    return 0 if info["outcome"] != "fallback" else 1


if __name__ == "__main__":
    raise SystemExit(main())
