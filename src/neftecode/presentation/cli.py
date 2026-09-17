"""Command-line presentation boundary.

The parser owns the stable command contract. Runtime wiring is supplied by the top-level
composition root so this layer does not depend on infrastructure or evaluation modules.
"""
import argparse
from collections.abc import Callable, Sequence
from pathlib import Path


COMMANDS = ("train", "demo", "advise", "snapshot", "vak", "episodes", "tank-check", "benchmark", "screen", "scenes", "serve",
            "agent-demo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Локальный исследовательский прототип Нефтекод")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    parser.add_argument("--config", type=Path, default=Path("config/experiment.json"))
    parser.add_argument("--at", help="Местное время решения для advise и snapshot, например 2026-01-05T08:00:00")
    parser.add_argument("--all", action="store_true",
                        help="snapshot: все моменты из config/snapshot_moments.json")
    parser.add_argument("--snapshot", help="serve/scenes: имя среза (ГГГГММДД-ЧЧММСС) или synthetic")
    parser.add_argument("--scenario", type=Path, help="Файл сценария для screen и agent-demo")
    parser.add_argument("--decision", type=Path, help="Сохранённое решение для повторного просмотра")
    parser.add_argument("--port", type=int, default=8765, help="Порт демонстрационного сервера")
    return parser


def main(argv: Sequence[str] | None = None,
         execute: Callable[[argparse.Namespace, argparse.ArgumentParser], object] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if execute is None:
        parser.error("Команды запускаются через исполняемый файл neftecode")
    return execute(args, parser)


if __name__ == "__main__":
    main()
