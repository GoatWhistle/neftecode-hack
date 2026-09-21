import time
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


_CODE_TTL_S = 30.0
_code_cache: dict[str, tuple[float, dict]] = {}


def code_version(root: str) -> dict:
    """Версия кода: коммит и признак изменённого дерева (только исходники и конфигурация, не документы).

    Значение живёт не дольше _CODE_TTL_S: долгоживущий сервер замечает новый коммит и правки дерева.
    """
    now = time.monotonic()
    hit = _code_cache.get(root)
    if hit is not None and now - hit[0] < _CODE_TTL_S:
        return hit[1]
    path = Path(root)
    commit = _git(path, "rev-parse", "HEAD")
    changed = _git(path, "status", "--porcelain", "--", "src/neftecode", "config", "pyproject.toml")
    value = {"commit": commit, "dirty": None if changed is None else bool(changed),
             "note": None if commit else "git недоступен: версия кода неизвестна"}
    _code_cache[root] = (now, value)
    return value


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


_model_cache: dict[tuple[str, str], tuple[tuple, dict]] = {}


def model_version(root: str, artifacts_dir: str | None = None) -> dict:
    """Версия модели отклика из того каталога артефактов, который фактически загружен сервисом."""
    directory = Path(artifacts_dir) if artifacts_dir is not None else Path(root) / "artifacts"
    model_path = directory / "response_model.json"
    manifest = directory / "manifest.json"
    stamp = (_stamp(model_path), _stamp(manifest))
    key = (root, str(directory))
    hit = _model_cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    training = None
    try:
        training = json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint")
    except (OSError, ValueError):
        pass
    value = {"response_model_sha256": _file_digest(model_path), "training_fingerprint": training}
    _model_cache[key] = (stamp, value)
    return value
