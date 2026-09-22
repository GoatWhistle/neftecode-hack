import json

import pandas as pd

from neftecode.application.history.prepare import HistoryError, local_moment
from neftecode.infrastructure.artifacts import clean
from neftecode.infrastructure.data.alignment import backward_readings

MAX_POINTS = 48
MAX_RESPONSE_BYTES = 262144


def bounded_response(payload: dict) -> dict:
    payload = clean(payload)
    if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESPONSE_BYTES:
        raise HistoryError("response_budget", "Ответ истории превышает 256 КиБ; уменьшите страницу или период")
    return payload


def observations(signals, lab, online, cfg, start: str, end: str, points: int) -> list[dict]:
    if type(points) is not int or not 1 <= points <= MAX_POINTS:
        raise HistoryError("invalid_budget", "Обзор содержит от 1 до 48 точек")
    first, last = local_moment(start), local_moment(end)
    if first > last:
        raise HistoryError("invalid_period", "Начало периода позже конца")
    times = pd.date_range(first, last, periods=points).as_unit("ns")
    telemetry = signals.reindex(times, method="ffill", tolerance=pd.Timedelta(value=20, unit="min"))
    labs = backward_readings(times, lab, cfg["lab_delay_hours"])
    pak = backward_readings(times, online)
    rows = []
    for i, at in enumerate(times):
        rows.append({"at": at.isoformat(), "lab_value": labs.iloc[i].value,
                     "lab_sample_time": labs.iloc[i].sample_time, "lab_available_time": labs.iloc[i].available_time,
                     "pak_value": pak.iloc[i].value, "pak_sample_time": pak.iloc[i].sample_time,
                     "telemetry_missing_fraction": float(telemetry.iloc[i].isna().mean())})
    return clean(rows)
