from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess

UNKNOWN = None


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return UNKNOWN


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    return done.stdout.strip() if done.returncode == 0 else UNKNOWN


@lru_cache(maxsize=4)
def code_version(root: str) -> dict:
    """Версия кода: коммит и признак изменённого дерева (только исходники и конфигурация, не документы)."""
    path = Path(root)
    commit = _git(path, "rev-parse", "HEAD")
    changed = _git(path, "status", "--porcelain", "--", "src/neftecode", "config", "pyproject.toml")
    return {"commit": commit, "dirty": None if changed is None else bool(changed),
            "note": None if commit else "git недоступен: версия кода неизвестна"}


@lru_cache(maxsize=4)
def model_version(root: str) -> dict:
    path = Path(root)
    manifest = path / "artifacts" / "manifest.json"
    training = None
    try:
        training = json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint")
    except (OSError, ValueError):
        pass
    return {"response_model_sha256": _file_digest(path / "artifacts" / "response_model.json"),
            "training_fingerprint": training}
