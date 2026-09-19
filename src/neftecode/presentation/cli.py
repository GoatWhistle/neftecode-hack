import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


COMMANDS = ("train", "demo", "advise", "snapshot", "vak", "episodes", "tank-check", "benchmark", "expert-grid", "screen", "scenes", "serve",
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
    parser.add_argument("--snapshot", help="serve: срез первого экрана (ГГГГММДД-ЧЧММСС) или synthetic; "
                                           "по умолчанию норма 05.01.2026, иначе свежайший")
    parser.add_argument("--scenario", type=Path, help="Файл сценария для screen и agent-demo")
    parser.add_argument("--decision", type=Path, help="Сохранённое решение для повторного просмотра")
    parser.add_argument("--port", type=int, default=8765, help="Порт демонстрационного сервера")
    parser.add_argument("--static", type=Path, default=None,
                        help="serve: каталог собранного фронтенда, по умолчанию src/frontend/dist")
    return parser


def use_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and getattr(stream, "encoding", "").lower() not in ("utf-8", "utf8"):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None,
         execute: Callable[[argparse.Namespace, argparse.ArgumentParser], object] | None = None):
    use_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if execute is None:
        parser.error("Команды запускаются через исполняемый файл neftecode")
    return execute(args, parser)


if __name__ == "__main__":
    main()
