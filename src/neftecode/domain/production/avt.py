from dataclasses import dataclass, field
import math

from neftecode.domain.production.scenario import Quantity, Scenario, Stage

IN_REGION, OUT_OF_REGION = "in_region", "out_of_region"


class ProcessError(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class StreamState:

    flow_tph: float
    sulfur_mgkg: float | None
    t95_c: float | None = None
    density_kgm3: float | None = None
    applicability: str = IN_REGION
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if not _finite(self.flow_tph) or self.flow_tph < 0:
            raise ProcessError("StreamState.flow_tph: расход должен быть конечным и неотрицательным")

    @property
    def usable(self) -> bool:
        return self.applicability == IN_REGION and self.sulfur_mgkg is not None

    def to_dict(self) -> dict:
        return {"flow_tph": self.flow_tph, "sulfur_mgkg": self.sulfur_mgkg, "t95_c": self.t95_c,
                "density_kgm3": self.density_kgm3, "applicability": self.applicability,
                "notes": list(self.notes)}


def _range_note(name: str, value: float, low: float, high: float) -> str | None:
    if value < low or value > high:
        return (f"{name} = {value:g} вне области модели [{low:g}, {high:g}]: "
                f"результат за пределами описанной применимости")
    return None


@dataclass(frozen=True)
class AvtModel:

    reference_temp_c: float
    yield_at_reference: float
    yield_per_degree: float
    sulfur_partition: float
    sulfur_per_degree: float
    t95_at_reference_c: float
    t95_per_degree: float
    temp_range_c: tuple[float, float]
    feed_range_tph: tuple[float, float]
    provenance: str = "scenario"

    @classmethod
    def from_stage(cls, stage: Stage) -> "AvtModel":
        model = stage.model or {}
        missing = [k for k in ("reference_temp_c", "yield_at_reference", "yield_per_degree",
                               "sulfur_partition", "sulfur_per_degree", "t95_at_reference_c",
                               "t95_per_degree") if k not in model]
        if missing:
            raise ProcessError(f"stages.avt.model: не заданы коэффициенты {', '.join(missing)}")
        temps = stage.control_range("avt_furnace_outlet_temp_c")
        feeds = stage.control_range("crude_feed_rate_tph")
        return cls(model["reference_temp_c"], model["yield_at_reference"], model["yield_per_degree"],
                   model["sulfur_partition"], model["sulfur_per_degree"],
                   model["t95_at_reference_c"], model["t95_per_degree"], temps, feeds)

    def run(self, crude: dict[str, Quantity], controls: dict[str, float]) -> StreamState:
        feed = controls.get("crude_feed_rate_tph", crude["flow_tph"].value)
        temp = controls["avt_furnace_outlet_temp_c"]
        for name, value in (("crude_feed_rate_tph", feed), ("avt_furnace_outlet_temp_c", temp)):
            if not _finite(value):
                raise ProcessError(f"avt.{name}: значение должно быть конечным числом")
        notes = [n for n in (_range_note("avt_furnace_outlet_temp_c", temp, *self.temp_range_c),
                             _range_note("crude_feed_rate_tph", feed, *self.feed_range_tph)) if n]
        delta = temp - self.reference_temp_c
        share = self.yield_at_reference * (1 + self.yield_per_degree * delta)
        if share <= 0:
            return StreamState(0.0, None, None, crude["density_kgm3"].value, OUT_OF_REGION,
                               ("Модель даёт неположительный выход дизельной фракции: "
                                "режим вне описанной области",))
        flow = feed * share
        crude_sulfur_mgkg = crude["sulfur_wt_pct"].value * 10_000
        sulfur = crude_sulfur_mgkg * self.sulfur_partition * (1 + self.sulfur_per_degree * delta)
        t95 = self.t95_at_reference_c + self.t95_per_degree * delta
        applicability = OUT_OF_REGION if notes else IN_REGION
        if sulfur < 0:
            sulfur, applicability = None, OUT_OF_REGION
            notes.append("Модель даёт отрицательную серу: результат недостоверен, значение неизвестно")
        return StreamState(flow, sulfur, t95, crude["density_kgm3"].value, applicability,
                           tuple(notes) + ("Отклик АВТ — сценарная модель с заданными коэффициентами, "
                                           "не измеренная реакция установки.",))

    def to_dict(self) -> dict:
        return {"kind": "scenario_linear_avt", "provenance": self.provenance,
                "reference_temp_c": self.reference_temp_c,
                "yield_at_reference": self.yield_at_reference,
                "yield_per_degree": self.yield_per_degree,
                "sulfur_partition": self.sulfur_partition,
                "sulfur_per_degree": self.sulfur_per_degree,
                "t95_at_reference_c": self.t95_at_reference_c,
                "t95_per_degree": self.t95_per_degree,
                "temp_range_c": list(self.temp_range_c), "feed_range_tph": list(self.feed_range_tph),
                "note": "Коэффициенты заданы сценарием. Направления зависимостей соответствуют "
                        "обычному поведению перегонки; величины не подтверждены данными завода."}


@dataclass
class AvtStage:

    scenario: Scenario
    model: AvtModel = field(init=False)

    def __post_init__(self):
        self.model = AvtModel.from_stage(self.scenario.stages["avt"])

    def current_controls(self) -> dict[str, float]:
        stage = self.scenario.stages["avt"]
        return {name: spec["current"].value for name, spec in stage.controls.items()}

    def run(self, controls: dict[str, float] | None = None) -> StreamState:
        merged = {**self.current_controls(), **(controls or {})}
        return self.model.run(self.scenario.crude, merged)
