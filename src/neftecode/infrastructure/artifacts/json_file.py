"""JSON serialization with the project's explicit missing-value policy."""

import json
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
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
