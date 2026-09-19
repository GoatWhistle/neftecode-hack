from dataclasses import dataclass
import math

from neftecode.domain.shared.primitives import SOURCES


SCHEMA = "neftecode.scenario.v1"


UNITS = {
    "sulfur_mgkg": "мг/кг",
    "t95_c": "°C",
    "cetane_number": "ед.",
    "density_kgm3": "кг/м3",
    "mass_t": "т",
    "flow_tph": "т/ч",
    "temperature_c": "°C",
    "pressure_mpa": "МПа",
    "volume_flow_m3h": "м3/ч",
    "sulfur_wt_pct": "% масс.",
    "fraction": "доля",
    "cost_per_t": "усл.ед./т",
    "cost_per_ppm2_per_t": "усл.ед./т/(мг/кг)²",
    "sulfur_per_degree": "мг/кг/°C",
    "hours": "ч",
}




class ScenarioError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Quantity:

    value: float
    unit: str
    source: str
    note: str | None = None

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "source": self.source, "note": self.note}

    @property
    def measured(self) -> bool:
        return self.source in ("given", "derived", "measured")


def quantity(raw, kind: str, where: str, *, allow_negative: bool = False) -> Quantity:
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where}: ожидается объект со значением, единицей и источником, получено {type(raw).__name__}")
    missing = [k for k in ("value", "unit", "source") if k not in raw]
    if missing:
        raise ScenarioError(f"{where}: не заданы обязательные поля {', '.join(missing)}")
    value = raw["value"]
    if not _finite(value):
        raise ScenarioError(f"{where}: значение должно быть конечным числом, получено {value!r}")
    if value < 0 and not allow_negative:
        raise ScenarioError(f"{where}: отрицательное значение {value} недопустимо для этой величины")
    expected = UNITS.get(kind)
    if expected is None:
        raise ScenarioError(f"{where}: неизвестный вид величины {kind}")
    if raw["unit"] != expected:
        raise ScenarioError(f"{where}: единица «{raw['unit']}» не совпадает с ожидаемой «{expected}»; "
                            f"пересчёт по догадке запрещён")
    if raw["source"] not in SOURCES:
        raise ScenarioError(f"{where}: источник «{raw['source']}» не из набора {', '.join(SOURCES)}")
    return Quantity(float(value), raw["unit"], raw["source"], raw.get("note"))


def optional_quantity(raw, kind: str, where: str) -> Quantity | None:
    return None if raw is None else quantity(raw, kind, where)
