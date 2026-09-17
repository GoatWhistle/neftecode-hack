"""Effect of an action on the chain: AVT, then hydrotreating.

This is deliberately NOT the forecast. The forecast answers "what is coming given the history";
this module answers "what would come out if this setpoint were moved". A CatBoost model with one
input swapped does not answer the second question, so it is not used here.

The relations below are scenario models with declared units, coefficients and an applicability
range. They are honest about being ours: the expert allowed the team to build its own justified
model, including a simple linear one (message 518). None of it is a measured plant response.

Everything works in the named physical variables of the process schemes
(`crude_feed_rate_tph`, `ht_reactor_inlet_temp_c`, …), never in the raw CSV tags, because the
magnitudes of the 24-2000 tags contradict their descriptions — see context/requirements-map.md.
"""
from dataclasses import dataclass, field
import math

from neftecode.domain.production.scenario import Quantity, Scenario, Stage

#: Result is inside the region the model was declared for.
IN_REGION, OUT_OF_REGION = "in_region", "out_of_region"


class ProcessError(ValueError):
    """Raised when a model is asked for something it does not claim to describe."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class StreamState:
    """Properties of a stream leaving one stage. Unknown stays unknown."""

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
    """Straight-run diesel cut leaving the AVT column.

    Structure, with every coefficient declared in the scenario:

        diesel_flow   = feed * yield_at_reference * (1 + dy_dT * (T_furnace - T_reference))
        diesel_sulfur = crude_sulfur_wt_pct * 10000 * partition
                        * (1 + ds_dT * (T_furnace - T_reference))
        diesel_t95    = t95_at_reference + dt95_dT * (T_furnace - T_reference)

    `partition` is the share of crude sulfur that ends up in the diesel cut. A heavier cut
    (higher furnace outlet) carries more sulfur and a higher T95: that direction is standard
    distillation behaviour, but the magnitudes here are ours, not measured.
    """

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
    """Convenience wrapper binding the model to one scenario."""

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


@dataclass(frozen=True)
class HydrotreatingModel:
    """Sulfur leaving the hydrotreater, and how long a setpoint change takes to show up.

    Structure, coefficients declared in the scenario:

        conversion = 1 - (1 - conversion_at_reference)
                         * exp(-dk_dT * (T_inlet - T_reference))
                         * (space_velocity / reference_space_velocity) ** severity_exponent
        outlet_sulfur = inlet_sulfur * (1 - conversion)

    Higher inlet temperature removes more sulfur; higher throughput leaves less residence time
    and removes less. Both directions are ordinary hydrotreating behaviour; the magnitudes are
    ours and carry no measured backing.

    **Delay is part of the model, not decoration.** `apply_at` returns the setpoint actually
    acting at a given time, so a change made now cannot improve the product now. Two successive
    changes are handled by taking the most recent one already in effect: adding their separate
    effects would count the same move twice.
    """

    reference_temp_c: float
    conversion_at_reference: float
    conversion_per_degree: float
    reference_space_velocity_m3h: float
    severity_exponent: float
    response_lag_hours: float
    temp_range_c: tuple[float, float]
    flow_range_m3h: tuple[float, float]
    t95_shift_per_degree: float = 0.0
    provenance: str = "scenario"

    @classmethod
    def from_stage(cls, stage: Stage) -> "HydrotreatingModel":
        model = stage.model or {}
        required = ("reference_temp_c", "conversion_at_reference", "conversion_per_degree",
                    "reference_space_velocity_m3h", "severity_exponent")
        missing = [k for k in required if k not in model]
        if missing:
            raise ProcessError(f"stages.hydrotreating.model: не заданы коэффициенты {', '.join(missing)}")
        if not 0 < model["conversion_at_reference"] < 1:
            raise ProcessError("stages.hydrotreating.model.conversion_at_reference: доля удаления серы "
                               "должна лежать строго между 0 и 1")
        return cls(model["reference_temp_c"], model["conversion_at_reference"],
                   model["conversion_per_degree"], model["reference_space_velocity_m3h"],
                   model["severity_exponent"], stage.response_lag_hours.value,
                   stage.control_range("ht_reactor_inlet_temp_c"),
                   stage.control_range("ht_feed_flow_m3h"),
                   model.get("t95_shift_per_degree", 0.0),
                   str(model.get("provenance", "scenario")))

    def effective_controls(self, time_hours: float, current: dict[str, float],
                           pending: tuple[tuple[float, dict[str, float]], ...] = ()) -> dict[str, float]:
        """Which setpoints are actually acting at `time_hours` after the decision.

        `pending` holds `(applied_at_hours, controls)` for confirmed moves. Only the latest
        move whose lag has elapsed is in effect: successive changes supersede each other
        rather than accumulating.
        """
        if not _finite(time_hours) or time_hours < 0:
            raise ProcessError("effective_controls: время должно быть конечным и неотрицательным")
        acting = dict(current)
        in_effect = [(at, controls) for at, controls in pending
                     if at + self.response_lag_hours <= time_hours + 1e-9]
        for _, controls in sorted(in_effect, key=lambda item: item[0]):
            acting.update(controls)
        return acting

    def run(self, feed: StreamState, controls: dict[str, float]) -> StreamState:
        temp = controls["ht_reactor_inlet_temp_c"]
        flow = controls["ht_feed_flow_m3h"]
        for name, value in (("ht_reactor_inlet_temp_c", temp), ("ht_feed_flow_m3h", flow)):
            if not _finite(value):
                raise ProcessError(f"hydrotreating.{name}: значение должно быть конечным числом")
        if flow <= 0:
            raise ProcessError("hydrotreating.ht_feed_flow_m3h: расход сырья должен быть положительным")
        notes = [n for n in (_range_note("ht_reactor_inlet_temp_c", temp, *self.temp_range_c),
                             _range_note("ht_feed_flow_m3h", flow, *self.flow_range_m3h)) if n]
        applicability = OUT_OF_REGION if notes else IN_REGION
        if feed.applicability == OUT_OF_REGION:
            applicability = OUT_OF_REGION
            notes.append("Входной поток пришёл из режима вне области модели АВТ")
        if feed.sulfur_mgkg is None:
            return StreamState(feed.flow_tph, None, feed.t95_c, feed.density_kgm3, OUT_OF_REGION,
                               tuple(notes) + ("Сера сырья гидроочистки неизвестна: "
                                               "результат не вычисляется",))
        remaining = ((1 - self.conversion_at_reference)
                     * math.exp(-self.conversion_per_degree * (temp - self.reference_temp_c))
                     * (flow / self.reference_space_velocity_m3h) ** self.severity_exponent)
        remaining = min(1.0, max(0.0, remaining))
        outlet = feed.sulfur_mgkg * remaining
        t95 = None if feed.t95_c is None else feed.t95_c + self.t95_shift_per_degree * (temp - self.reference_temp_c)
        return StreamState(feed.flow_tph, outlet, t95, feed.density_kgm3, applicability,
                           tuple(notes) + (f"Доля оставшейся серы {remaining:.4f} по сценарной модели "
                                           f"гидроочистки; измеренной реакцией установки не является.",
                                           f"Объявленное запаздывание отклика {self.response_lag_hours:g} ч.",))

    def to_dict(self) -> dict:
        return {"kind": "scenario_kinetic_hydrotreating", "provenance": self.provenance,
                "reference_temp_c": self.reference_temp_c,
                "conversion_at_reference": self.conversion_at_reference,
                "conversion_per_degree": self.conversion_per_degree,
                "reference_space_velocity_m3h": self.reference_space_velocity_m3h,
                "severity_exponent": self.severity_exponent,
                "response_lag_hours": self.response_lag_hours,
                "temp_range_c": list(self.temp_range_c), "flow_range_m3h": list(self.flow_range_m3h),
                "note": ("Наклон отклика по температуре выведен из данных завода (линеаризация в конверте "
                         "исследования); опорная точка — измерение на момент решения. Это модель "
                         "последствий действия, а не прогноз по истории."
                         if self.provenance == "derived" else
                         "Коэффициенты заданы сценарием. Направления соответствуют обычному поведению "
                         "гидроочистки; величины не подтверждены данными завода. Это модель "
                         "последствий действия, а не прогноз по истории.")}


@dataclass
class ChainModel:
    """AVT and hydrotreating in sequence, with the delay of each stage respected."""

    scenario: Scenario
    avt: AvtStage = field(init=False)
    hydrotreating: HydrotreatingModel = field(init=False)

    def __post_init__(self):
        self.avt = AvtStage(self.scenario)
        self.hydrotreating = HydrotreatingModel.from_stage(self.scenario.stages["hydrotreating"])

    def current_controls(self) -> dict[str, float]:
        controls = dict(self.avt.current_controls())
        for name, spec in self.scenario.stages["hydrotreating"].controls.items():
            controls[name] = spec["current"].value
        return controls

    def run_at(self, time_hours: float, pending=(), controls: dict[str, float] | None = None) -> StreamState:
        """Chain output at `time_hours` after the decision, given confirmed pending moves.

        A move proposed now reaches the product only after its stage's lag, so the output at
        `time_hours = 0` equals the output of the regime that was already running.
        """
        base = {**self.current_controls(), **(controls or {})}
        avt_stage = self.scenario.stages["avt"]
        avt_lag = avt_stage.response_lag_hours.value
        avt_acting = dict(base)
        for at, moves in sorted(pending, key=lambda item: item[0]):
            if at + avt_lag <= time_hours + 1e-9:
                avt_acting.update({k: v for k, v in moves.items() if k in avt_stage.controls})
        cut = self.avt.model.run(self.scenario.crude, avt_acting)
        ht_acting = self.hydrotreating.effective_controls(
            time_hours, base, tuple((at, {k: v for k, v in moves.items()
                                          if k in self.scenario.stages["hydrotreating"].controls})
                                    for at, moves in pending))
        return self.hydrotreating.run(cut, ht_acting)

    def to_dict(self) -> dict:
        return {"avt": self.avt.model.to_dict(), "hydrotreating": self.hydrotreating.to_dict(),
                "note": "Модель последствий управляющего действия. Прогноз по истории — "
                        "отдельный компонент; подмена одного другим запрещена."}
