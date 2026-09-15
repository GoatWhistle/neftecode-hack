"""Dispatch parsed CLI commands to their composition modules."""
from neftecode.presentation import cli

from . import agentic, demo, evaluation, live, screens, training

HANDLERS = {
    "train": training.handle,
    "demo": demo.demo,
    "serve": demo.serve,
    "screen": screens.screen,
    "scenes": screens.scenes,
    "benchmark": evaluation.benchmark,
    "episodes": evaluation.episodes,
    "vak": evaluation.vak,
    "advise": live.handle,
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
