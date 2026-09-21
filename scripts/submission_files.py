"""Print the tracked submission manifest as NUL-separated paths for tar.

Only reviewed public roots are allowed. Local work logs and editor/agent settings
stay on disk and must never enter a release through a new tracked root.
"""
from pathlib import PurePosixPath
import subprocess
import sys


ROOT_FILES = {
    ".dockerignore", ".gitignore", ".python-version", "LICENSE", "README.md",
    "docker-compose.yml", "docker-compose.offline.yml", "pyproject.toml", "uv.lock",
}
PUBLIC_DIRS = {"src", "tests", "config", "scripts", "docs", "research"}
PRIVATE_PARTS = {
    ".git", ".claude", ".idea", "context", "node_modules", "__pycache__",
    ".pytest_cache", ".venv", "AGENTS.md", "CLAUDE.md", ".env",
}


def main() -> None:
    paths = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")
    for raw in paths:
        if not raw:
            continue
        path = PurePosixPath(raw.decode("utf-8"))
        if (str(path) in ROOT_FILES or path.parts[0] in PUBLIC_DIRS) and not (
            set(path.parts) & PRIVATE_PARTS or path.suffix in {".log", ".tmp"}
        ):
            sys.stdout.buffer.write(raw + b"\0")


if __name__ == "__main__":
    main()
