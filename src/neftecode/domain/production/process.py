from dataclasses import dataclass, field
import math

from neftecode.domain.production.scenario import Scenario, Stage

from .avt import (AvtModel, AvtStage, IN_REGION, OUT_OF_REGION, ProcessError, StreamState, _finite,
                  _range_note)

__all__ = ["AvtModel", "AvtStage", "ChainModel", "HydrotreatingModel", "IN_REGION", "OUT_OF_REGION",
           "ProcessError", "StreamState"]


@dataclass(frozen=True)
class HydrotreatingModel:

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
    horizon_response_share: float = 1.0
    horizon_response_until_hours: float = 0.0

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
        share = model.get("horizon_response_share", 1.0)
        until = model.get("horizon_response_until_hours", 0.0)
        if not _finite(share) or not 0 < share <= 1 or not _finite(until) or until < 0:
            raise ProcessError("stages.hydrotreating.model.horizon_response_share: доля хода в пределах горизонта "
                               "должна лежать в (0, 1], horizon_response_until_hours — быть неотрицательным")
        return cls(model["reference_temp_c"], model["conversion_at_reference"],
                   model["conversion_per_degree"], model["reference_space_velocity_m3h"],
                   model["severity_exponent"], stage.response_lag_hours.value,
                   stage.control_range("ht_reactor_inlet_temp_c"),
                   stage.control_range("ht_feed_flow_m3h"),
                   model.get("t95_shift_per_degree", 0.0),
                   str(model.get("provenance", "scenario")),
                   float(share), float(until))

    def effective_controls(self, time_hours: float, current: dict[str, float],
                           pending: tuple[tuple[float, dict[str, float]], ...] = ()) -> dict[str, float]:
        if not _finite(time_hours) or time_hours < 0:
            raise ProcessError("effective_controls: время должно быть конечным и неотрицательным")
        acting = dict(current)
        in_effect = [(at, controls) for at, controls in pending
                     if at + self.response_lag_hours <= time_hours + 1e-9]
        for _, controls in sorted(in_effect, key=lambda item: item[0]):
            acting.update(controls)
        partial = self.horizon_response_share < 1 and time_hours <= self.horizon_response_until_hours + 1e-9
        if partial and "ht_reactor_inlet_temp_c" in acting and "ht_reactor_inlet_temp_c" in current:
            start = current["ht_reactor_inlet_temp_c"]
            acting["ht_reactor_inlet_temp_c"] = start + self.horizon_response_share * (acting["ht_reactor_inlet_temp_c"] - start)
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
                "horizon_response_share": self.horizon_response_share,
                "horizon_response_until_hours": self.horizon_response_until_hours,
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
