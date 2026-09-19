import numpy as np
import pandas as pd

from .alignment import check_time_assumptions


QUALITY_HISTORY_HOURS = 72
LEGACY_FROZEN_READINGS = 6
DEFAULT_PAK_PERIOD_MINUTES = 10.0


def frozen_rule(cfg: dict) -> tuple[int, float]:
    readings = int(cfg.get("pak_frozen_readings", LEGACY_FROZEN_READINGS))
    period = float(cfg.get("pak_period_minutes", DEFAULT_PAK_PERIOD_MINUTES))
    if readings < 2 or not np.isfinite(period) or period <= 0:
        raise ValueError("pak_frozen_readings >= 2 и pak_period_minutes > 0 обязательны")
    return readings, period


def conflict_mask(pak_at_lab, lab_value, cfg: dict):
    difference = np.abs(np.asarray(pak_at_lab, dtype=float) - np.asarray(lab_value, dtype=float))
    threshold = cfg.get("pak_conflict_mgkg")
    if threshold is None:
        return difference > np.maximum(3, .5 * np.asarray(lab_value, dtype=float))
    return difference > float(threshold)


def _untrusted_runs(values: pd.Series, cfg: dict | None = None) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=bool)
    readings, _ = frozen_rule(cfg or {})
    changed = values.diff().abs().gt(1e-6) | values.diff().isna()
    run = changed.cumsum()
    return run.groupby(run).transform("size").ge(readings)


def derive_source_rules(signals: pd.DataFrame, lab: pd.DataFrame, online: pd.DataFrame, until,
                        cfg: dict) -> dict:
    method = {"lab_age_intervals": 2, "pak_age_periods": 3, "frozen_run_rarity": 0.001,
              "conflict_quantile": 0.95, "missing_rule": "histogram_valley", **cfg.get("source_rule_method", {})}
    until = pd.Timestamp(until)
    lab_part = lab[lab.time < until].sort_values("time")
    pak_part = online[online.time < until].sort_values("time")
    if len(lab_part) < 10 or len(pak_part) < 100:
        raise ValueError("Недостаточно истории для вывода порогов доверия к источникам")
    lab_interval = float(lab_part.time.diff().dt.total_seconds().dropna().median() / 3600)
    pak_period = float(pak_part.time.diff().dt.total_seconds().dropna().median() / 60)

    values = pak_part.set_index("time").value
    changed = values.diff().abs().gt(1e-6) | values.diff().isna()
    runs = values.groupby(changed.cumsum()).size()
    frozen_readings = 2
    while (runs >= frozen_readings).mean() > method["frozen_run_rarity"]:
        frozen_readings += 1

    joined = pd.merge_asof(lab_part, pak_part.rename(columns={"value": "pak"}), on="time", direction="backward",
                           tolerance=pd.Timedelta(value=pak_period * method["pak_age_periods"], unit="m")).dropna()
    conflict = float((joined.pak - joined.value).abs().quantile(method["conflict_quantile"]))

    telemetry = signals[signals.index < until]
    missing_counts = telemetry.isna().sum(axis=1).value_counts().reindex(range(telemetry.shape[1] + 1), fill_value=0)
    normal_mode = int(missing_counts.idxmax())
    largest = int(missing_counts[missing_counts > 0].index.max())
    upper = missing_counts.loc[max(normal_mode + 2, largest // 2):largest]
    outage_mode = int(upper.idxmax()) if len(upper) else largest + 1
    gap = missing_counts.loc[normal_mode + 1:max(normal_mode + 1, outage_mode - 1)]
    valley = int(gap.idxmin())
    missing = (valley - 1) / telemetry.shape[1]
    return {
        "lab_max_age_hours": round(method["lab_age_intervals"] * lab_interval, 3),
        "pak_max_age_minutes": round(method["pak_age_periods"] * pak_period, 3),
        "pak_period_minutes": round(pak_period, 3),
        "pak_frozen_readings": int(frozen_readings),
        "pak_conflict_mgkg": round(conflict, 3),
        "telemetry_max_missing_fraction": round(missing, 4),
        "source_rules": {
            "derived_until": until.isoformat(), "method": method,
            "observed": {"lab_median_interval_hours": lab_interval, "pak_median_period_minutes": pak_period,
                         "lab_samples": int(len(lab_part)), "paired_samples": int(len(joined)),
                         "pak_runs": int(len(runs)), "telemetry_rows": int(len(telemetry)),
                         "telemetry_columns": int(telemetry.shape[1]), "missing_normal_mode": normal_mode,
                         "missing_outage_mode": outage_mode, "missing_valley": valley},
            "note": ("Пороги выведены из истории до конца обучающего периода по объявленному методу; "
                     "организаторы численных порогов не давали."),
        },
    }


def recent_quality_history(lab: pd.DataFrame, online: pd.DataFrame, when, cfg: dict) -> dict:
    bounds = check_time_assumptions(cfg)
    when = pd.Timestamp(when)
    start = when - pd.Timedelta(value=QUALITY_HISTORY_HOURS, unit="h")
    p = online.set_index("time").value
    readings, period = frozen_rule(cfg)
    lookback = pd.Timedelta(value=readings * period, unit="m")
    part = p[(p.index > start - lookback) & (p.index <= when)]
    untrusted = _untrusted_runs(part, cfg)
    trusted = part[~untrusted & (part.index > start)]
    hourly = trusted.groupby(trusted.index.floor("h")).agg(["mean", "count"])
    steps = part.index.to_series().diff().dt.total_seconds().dropna()
    per_hour = float(3600 / steps.median()) if len(steps) and steps.median() > 0 else None
    available = lab.time + pd.Timedelta(value=bounds["lab_delay_hours"], unit="h")
    recent_lab = lab[(lab.time > start) & (available <= when)]
    known = part[~untrusted]
    return {
        "quality_history_hours": QUALITY_HISTORY_HOURS,
        "pak_last_trusted_value": float(known.iloc[-1]) if len(known) else None,
        "pak_last_trusted_time": known.index[-1].isoformat() if len(known) else None,
        "pak_trusted_hourly": [[t.isoformat(), float(row["mean"]), int(row["count"])]
                               for t, row in hourly.iterrows()],
        "pak_expected_per_hour": per_hour,
        "lab_recent": [[t.isoformat(), float(v)] for t, v in zip(recent_lab.time, recent_lab.value)],
    }
