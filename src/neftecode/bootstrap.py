from neftecode.composition.commands.dispatcher import execute, main as _main
from neftecode.composition.decision import (
    make_demo_service,
    make_interactive_demo,
    run_demo_decision,
)
from neftecode.composition.demo import make_demo, risk_alarm
from neftecode.composition.training import train
from neftecode.infrastructure.artifacts import clean, fingerprint, write_json

__all__ = [
    "clean", "execute", "fingerprint", "make_demo", "make_demo_service",
    "make_interactive_demo", "risk_alarm", "run_demo_decision", "train", "write_json", "main",
]


def main(argv=None):
    return _main(argv)


if __name__ == "__main__":
    main()
