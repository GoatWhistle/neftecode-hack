"""The CLI owns parsing while the composition root supplies command execution."""
from neftecode.presentation.cli import main


def test_cli_delegates_the_parsed_command_to_an_injected_executor(tmp_path):
    received = []

    def execute(args, parser):
        received.append((args.command, args.out, parser is not None))

    main(["screen", "--out", str(tmp_path)], execute=execute)
    assert received == [("screen", tmp_path, True)]
