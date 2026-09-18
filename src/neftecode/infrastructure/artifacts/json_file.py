"""JSON serialization with the project's explicit missing-value policy."""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def write_json(path: Path, obj) -> None:
    write_atomic(path, json.dumps(clean(obj), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_atomic(path: Path, content: str | bytes) -> None:
    """Write through a temporary file and `os.replace`, so an interrupted run leaves the old file intact.

    A half-written `model.pkl` or snapshot is exactly the kind of artifact that later fails with a
    pickle or JSON traceback; the replace is atomic on the same filesystem.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(content, bytes):
        tmp.write_bytes(content)
    else:
        tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
