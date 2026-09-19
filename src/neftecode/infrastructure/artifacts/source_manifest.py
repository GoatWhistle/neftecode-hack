
import hashlib
import json
import platform
from pathlib import Path


def fingerprint(root: Path, cfg):
    files = [*sorted((root / "task/data").glob("*.csv")), *sorted((root / "task").glob("*.xlsx")),
             *sorted((root / "src/neftecode").rglob("*.py")), root / "uv.lock"]
    hashes = {}
    for path in files:
        with path.open("rb") as stream:
            hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    key = hashlib.sha256(json.dumps([hashes, cfg], sort_keys=True).encode()).hexdigest()
    return {"fingerprint": key, "files": hashes, "config": cfg, "python": platform.python_version()}
