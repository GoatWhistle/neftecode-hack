from neftecode.presentation import cli

from . import agentic, demo, evaluation, live, screens, training

HANDLERS = {
    "train": training.handle,
    "demo": demo.demo,
    "serve": demo.serve,
    "screen": screens.screen,
    "scenes": screens.scenes,
    "benchmark": evaluation.benchmark,
    "expert-grid": evaluation.expert_grid,
    "episodes": evaluation.episodes,
    "tank-check": evaluation.tank_check,
    "vak": evaluation.vak,
    "advise": live.handle,
    "snapshot": live.snapshot,
    "agent-demo": agentic.agent_demo,
}


def execute(args, parser):
    root = args.root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        return HANDLERS[args.command](args, parser, root, out)
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"Ошибка: {exc}\n")


def main(argv=None):
    return cli.main(argv=argv, execute=execute)
