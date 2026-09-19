from pathlib import Path

import pytest

from neftecode.composition.commands.dispatcher import HANDLERS
from neftecode.presentation.cli import COMMANDS, build_parser, main


def test_cli_delegates_the_parsed_command_to_an_injected_executor(tmp_path):
    received = []

    def execute(args, parser):
        received.append((args.command, args.out, parser is not None))

    main(["screen", "--out", str(tmp_path)], execute=execute)
    assert received == [("screen", tmp_path, True)]


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_every_published_command_parses_and_has_a_handler(command: str) -> None:
    args = build_parser().parse_args([command])
    assert args.command == command
    assert command in HANDLERS


def test_the_three_late_commands_are_part_of_the_contract() -> None:
    for command in ("snapshot", "tank-check", "agent-demo"):
        assert command in COMMANDS, command
        assert command in HANDLERS, command
        assert build_parser().parse_args([command]).command == command


def test_an_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["not-a-command"])


def test_path_options_are_parsed_as_paths() -> None:
    args = build_parser().parse_args(
        ["screen", "--root", "r", "--out", "o", "--config", "c.json",
         "--scenario", "s.json", "--decision", "d.json", "--static", "dist"]
    )
    assert args.root == Path("r") and args.out == Path("o") and args.config == Path("c.json")
    assert args.scenario == Path("s.json") and args.decision == Path("d.json")
    assert args.static == Path("dist")


def test_port_is_parsed_as_an_integer_and_defaults_to_8765() -> None:
    assert build_parser().parse_args(["serve"]).port == 8765
    assert build_parser().parse_args(["serve", "--port", "9001"]).port == 9001
    with pytest.raises(SystemExit):
        build_parser().parse_args(["serve", "--port", "нет"])


def test_defaults_match_the_documented_contract() -> None:
    args = build_parser().parse_args(["demo"])
    assert args.out == Path("artifacts")
    assert args.config == Path("config/experiment.json")
    assert args.root == Path.cwd()
    assert args.at is None and args.snapshot is None and args.static is None
    assert args.all is False


def test_all_is_a_flag_without_a_value() -> None:
    assert build_parser().parse_args(["snapshot", "--all"]).all is True
    assert build_parser().parse_args(["snapshot"]).all is False


def test_main_without_an_executor_refuses_instead_of_running_anything() -> None:
    with pytest.raises(SystemExit):
        main(["demo"])
