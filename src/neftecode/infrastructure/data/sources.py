from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd


def series_frame(records: list[tuple], name: str) -> pd.DataFrame:
    frame = pd.DataFrame(records, columns=["time", "value"])
    frame["time"] = pd.to_datetime(frame.time, errors="raise")
    frame["value"] = pd.to_numeric(frame.value, errors="coerce")
    if frame.time.isna().any() or not np.isfinite(frame.value).all():
        raise ValueError(f"{name}: некорректное время или значение измерения; источник требует проверки")
    if (frame.value < 0).any():
        raise ValueError(f"{name}: отрицательная сера, требуется разбор источника")
    if frame.groupby("time").value.nunique().gt(1).any():
        raise ValueError(f"{name}: противоречивые дубликаты времени")
    return frame.drop_duplicates("time").sort_values("time").reset_index(drop=True)


STUB_VALUE = 307.0
DEAD_COLUMN_STUB_SHARE = 0.9


def mask_stubs(signals: pd.DataFrame, until=None) -> tuple[pd.DataFrame, list[str]]:
    masked = signals.mask(signals == STUB_VALUE)
    basis = signals if until is None else signals[signals.index < pd.Timestamp(until)]
    if basis.empty:
        raise ValueError("Нет строк телеметрии до границы отбора мёртвых колонок")
    dead = [c for c in masked.columns if (basis[c] == STUB_VALUE).mean() > DEAD_COLUMN_STUB_SHARE]
    return masked.drop(columns=dead), dead


def _single_file(task: Path, pattern: str, what: str) -> Path:
    found = sorted(task.glob(pattern))
    if not found:
        raise FileNotFoundError(f"В {task} нет файла {pattern}: положите {what} организаторов рядом с data/ "
                                f"(состав task/ описан в README)")
    return found[0]


def load_sources(task: Path, dead_until=None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    telemetry = []
    for filename, prefix in [("avt_tags.csv", "avt"), ("242000_tags.csv", "ht")]:
        frame = pd.read_csv(task / "data" / filename)
        frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed:")]
        frame["date"] = pd.to_datetime(frame.date, errors="raise")
        if frame.date.duplicated().any():
            raise ValueError(f"{filename}: дубликаты времени")
        frame = frame.set_index("date").sort_index().astype(float)
        telemetry.append(frame.add_prefix(prefix + "."))
    signals = pd.concat(telemetry, axis=1).sort_index().replace([np.inf, -np.inf], np.nan)
    signals, _ = mask_stubs(signals, dead_until)

    book = openpyxl.load_workbook(_single_file(task, "ЛИМС*.xlsx", "выгрузку ЛИМС"), read_only=True, data_only=True)
    rows = list(book.active.values)
    if rows[1][94] != "Mg.Sulfur" or rows[2][94] != "мг/кг":
        raise ValueError("ЛИМС CQ:CR: изменилась схема целевого показателя")
    lab = series_frame([(r[94], r[95]) for r in rows[4:] if isinstance(r[94], datetime)], "ЛИМС")
    book.close()

    book = openpyxl.load_workbook(_single_file(task, "Выгрузка*.xlsx", "выгрузку ПАК"), read_only=True, data_only=True)
    rows = iter(book.active.values)
    names, units = next(rows), next(rows)
    if "Mg.Sulfur" not in str(names[0]) or units[0] != "ppm":
        raise ValueError("ПАК A:B: изменилась схема серы")
    online = series_frame([(r[0], r[1]) for r in rows if isinstance(r[0], datetime)], "ПАК")
    book.close()
    return signals, lab, online
