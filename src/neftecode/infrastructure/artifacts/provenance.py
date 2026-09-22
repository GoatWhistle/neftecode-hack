from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

UNKNOWN = None


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    return done.stdout.strip() if done.returncode == 0 else UNKNOWN


def code_version(root: str | Path) -> dict:
    """Версия кода сейчас: коммит и признак изменённого дерева (только исходники и конфигурация)."""
    path = Path(root)
    commit = _git(path, "rev-parse", "HEAD")
    changed = _git(path, "status", "--porcelain", "--", "src/neftecode", "config", "pyproject.toml")
    return {"commit": commit, "dirty": None if changed is None else bool(changed),
            "note": None if commit else "git недоступен: версия кода неизвестна"}


def training_fingerprint(artifacts_dir: str | Path) -> str | None:
    try:
        value = json.loads((Path(artifacts_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNKNOWN
    return value.get("fingerprint") if isinstance(value, dict) else UNKNOWN


def loaded_provenance(root: str | Path, artifacts_dir: str | Path, response_model_sha256: str | None) -> dict:
    """Происхождение расчёта, закреплённое при создании сервиса вместе с загруженной моделью.

    Хеш модели — от тех байтов, которые сервис разобрал (load_response_model_with_digest), а не от
    файла на диске в момент ответа. Версия кода — состояние дерева при запуске процесса: новый коммит
    после запуска не исполняется уже работающим Python. Обновляется только перезапуском сервиса.
    """
    loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    code = {**code_version(root), "captured": "process_start", "captured_at": loaded_at}
    model = {"response_model_sha256": response_model_sha256,
             "training_fingerprint": training_fingerprint(artifacts_dir),
             "loaded_at": loaded_at, "source": "loaded_by_computing_process"}
    return {"code": code, "model": model}
