"""Shared loaders for the response-model research. Cached to the scratchpad-free local `out/cache.pkl`.

Reads the raw task files with the project's own readers, so research data equals production data.
"""
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))

from neftecode.infrastructure.data.data import load_sources  # noqa: E402

CACHE = OUT / "cache.pkl"

#: LIMS columns of interest: (column index of time, name). Value is the next column.
LIMS_COLUMNS = {
    "ht_in_t95": 72, "ht_in_t90": 66, "ht_in_t50": 70, "ht_in_ibp": 68, "ht_in_ebp": 76,
    "ht_in_cloud": 74, "ht_in_sulfur_pct": 80, "ht_in_d15": 78,
    "ht_out_sulfur": 94, "ht_out_t95": 92, "ht_out_d15": 84, "ht_out_flash": 86,
    "avt3_t95": 56, "avt3_t50": 52,
}


def _lims_extra(task: Path) -> dict[str, pd.DataFrame]:
    import openpyxl
    book = openpyxl.load_workbook(next(task.glob("ЛИМС*.xlsx")), read_only=True, data_only=True)
    rows = list(book.active.values)
    book.close()
    out = {}
    for name, col in LIMS_COLUMNS.items():
        rec = [(r[col], r[col + 1]) for r in rows[4:]
               if isinstance(r[col], datetime) and isinstance(r[col + 1], (int, float))]
        f = pd.DataFrame(rec, columns=["time", "value"])
        f["time"] = pd.to_datetime(f.time)
        out[name] = f.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return out


def load(refresh: bool = False):
    """signals (10-min, prefixed avt./ht.), lab sulfur, online PAK (raw), extra LIMS dict."""
    if CACHE.exists() and not refresh:
        with CACHE.open("rb") as s:
            return pickle.load(s)
    signals, lab, online = load_sources(ROOT / "task")
    extra = _lims_extra(ROOT / "task")
    data = (signals, lab, online, extra)
    with CACHE.open("wb") as s:
        pickle.dump(data, s)
    return data


def pak_on_grid(online: pd.DataFrame, index: pd.DatetimeIndex, how: str = "mean") -> pd.Series:
    """PAK aggregated to the 10-min telemetry grid (right-labelled, closed right: only past readings)."""
    p = online.set_index("time").value
    g = p.resample("10min", label="right", closed="right").agg(how)
    return g.reindex(index)


def flat_mask(series: pd.Series, hours: float = 1.0) -> pd.Series:
    """True where the value sits inside a flat run lasting >= hours (frozen instrument)."""
    changed = series.diff().abs().gt(1e-6) | series.diff().isna()
    run = changed.cumsum()
    t = series.index.to_series()
    span = t.groupby(run).transform("max") - t.groupby(run).transform("min")
    return span.ge(pd.Timedelta(hours=hours))


#: State features of the response dataset (known at decision time t). Shared by s5+.
STATE = ["T_in", "T_out", "dT_reactor", "feed", "P", "dP", "h2oil", "gas2", "gas22", "gas25", "quench", "density",
         "T_in_d6", "feed_d6", "h2oil_d6", "gas22_d6", "T_rel7d", "T_in_7d", "feed_7d", "cycle_age_d",
         "s_1h", "s_trend", "s_6h", "s_24h", "s_std6h", "s_last", "lab_s", "lab_s_age_h",
         "ht_in_t95", "ht_in_t95_age_h", "ht_in_t50", "ht_in_ebp", "ht_in_cloud"]
