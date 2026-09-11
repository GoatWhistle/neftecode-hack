"""Where the estimate of each product quality actually comes from, and where it does not.

The brief requires sulfur, and the experts added T95 and cetane number. These three are not
in the same position, and pretending otherwise would be the easiest way to produce a confident
number with nothing behind it:

* **sulfur** — 1 462 laboratory analyses. A forecast is trained and verified chronologically.
* **T95** — 1 291 analyses at the same sampling point. A forecast can be trained the same way;
  the published virtual analyser cannot be used (T07: its input has no declared lab point).
* **cetane number** — 42 analyses in the whole package. No model is claimed. The value comes
  from the scenario or stays unknown.

`unknown` is a real answer here. A quality with no estimate blocks the plan through the gate;
it never becomes a pass.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

#: Sampling point confirmed by the expert for the online sulfur analyser (message 517).
#: Its laboratory columns are the ones the product spec is judged against.
HYDROTREATING_POINT_2 = {
    "sulfur_mgkg": ("Mg.Sulfur", 94),
    "t95_c": ("95%.T", 92),
    "cetane_number": ("CetaneNumber", 102),
}

#: Fewer analyses than this and we do not claim a trained model for the property.
MIN_ANALYSES_FOR_A_MODEL = 200

#: How an estimate may be obtained, in decreasing order of standing.
VERIFIED_FORECAST = "verified_forecast"
SCENARIO_VALUE = "scenario_value"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class QualitySource:
    """What may be said about one product quality, and on what basis."""

    quality: str
    method: str
    n_analyses: int
    reason: str
    limitations: tuple[str, ...] = ()

    @property
    def has_model(self) -> bool:
        return self.method == VERIFIED_FORECAST

    def to_dict(self) -> dict:
        return {"quality": self.quality, "method": self.method, "n_analyses": self.n_analyses,
                "reason": self.reason, "limitations": list(self.limitations)}


def read_quality_series(task: Path) -> dict[str, pd.DataFrame]:
    """Read the three target qualities as independent time series from the laboratory export."""
    import openpyxl
    book = openpyxl.load_workbook(next(Path(task).glob("ЛИМС*.xlsx")), read_only=True, data_only=True)
    rows = list(book.active.values)
    book.close()
    names = rows[1]
    out = {}
    for quality, (expected, column) in HYDROTREATING_POINT_2.items():
        if names[column] != expected:
            raise ValueError(f"ЛИМС, колонка {column}: ожидался показатель «{expected}», "
                             f"найден «{names[column]}»; схема файла изменилась")
        records = [(r[column], r[column + 1]) for r in rows[4:]
                   if isinstance(r[column], datetime) and isinstance(r[column + 1], (int, float))]
        frame = pd.DataFrame(records, columns=["time", "value"])
        frame["time"] = pd.to_datetime(frame.time)
        out[quality] = frame.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return out


def classify_sources(series: dict[str, pd.DataFrame]) -> dict[str, QualitySource]:
    """Decide, per quality, whether a trained forecast may be claimed at all."""
    sources = {}
    for quality, frame in series.items():
        n = 0 if frame is None else len(frame)
        if n >= MIN_ANALYSES_FOR_A_MODEL:
            sources[quality] = QualitySource(
                quality, VERIFIED_FORECAST, n,
                f"{n} лабораторных анализов: прогноз обучается и проверяется по времени",
                ("Проверка на хронологических периодах; 2026 год уже просматривался и не является "
                 "новым слепым тестом.",))
        else:
            sources[quality] = QualitySource(
                quality, UNKNOWN, n,
                f"Всего {n} лабораторных анализов: обученная модель по ним не заявляется",
                ("Значение берётся из сценария и помечается как допущение, либо остаётся неизвестным.",
                 "Неизвестное критическое свойство блокирует план, а не проходит проверку."))
    return sources


def available_estimate(quality: str, sources: dict[str, QualitySource], scenario_value=None) -> dict:
    """The single answer for one quality at decision time: forecast, scenario value or unknown."""
    source = sources.get(quality)
    if source is not None and source.has_model:
        return {"quality": quality, "method": VERIFIED_FORECAST, "value": None,
                "note": "Значение даёт проверенный прогноз"}
    if scenario_value is not None:
        return {"quality": quality, "method": SCENARIO_VALUE, "value": float(scenario_value),
                "note": "Значение задано сценарием и не является измерением или прогнозом"}
    return {"quality": quality, "method": UNKNOWN, "value": None,
            "note": "Оценка недоступна: ни проверенного прогноза, ни заданного сценарием значения"}


def report(task: Path) -> dict:
    """Machine-readable statement of what the system can and cannot estimate."""
    series = read_quality_series(task)
    sources = classify_sources(series)
    return {
        "point": "Гидроочистка, точка отбора 2",
        "sources": {k: v.to_dict() for k, v in sources.items()},
        "modelled": sorted(k for k, v in sources.items() if v.has_model),
        "not_modelled": sorted(k for k, v in sources.items() if not v.has_model),
        "rule": f"Обученная модель заявляется только при {MIN_ANALYSES_FOR_A_MODEL} и более анализах. "
                f"Виртуальный анализатор источником значения не служит: см. context/vak-review.md.",
    }
