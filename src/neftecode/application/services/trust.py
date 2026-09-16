"""Whether the inputs deserve to carry a decision, and what to do when they do not.

Three positions are kept apart on purpose:

* a source is **usable** — fresh, self-consistent and not contradicted;
* a source is **suspect** — something is odd but not proven wrong, so it may still be
  reported while losing the right to be the only basis of a recommendation;
* a source is **unusable** — it cannot support a decision, and the reason says what is missing.

A telemetry value of exactly 307 is a polling stub (experts, chat message 582) and is already replaced by a
missing value when the sources are loaded; here it is still flagged if it reaches a state. A negative
reading is not deleted automatically: for vacuum and zero offsets it can be physically real.
"""
from dataclasses import dataclass, field
import math

#: Verdicts a single source can receive.
OK, SUSPECT, UNUSABLE, MISSING = "ok", "suspect", "unusable", "missing"

#: Priority given by the brief, section 2. It does not change with predictive accuracy.
SOURCE_PRIORITY = ("ЛИМС", "ПАК")

#: Repeated exactly in 64 of 71 AVT tags and in 15 of 26 tags of 24-2000; suspected export
#: placeholder, never confirmed. See context/requirements-map.md, section 6.
PLACEHOLDER_VALUE = 307.0


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class SourceVerdict:
    """One source at one moment, with its age and every reason it lost trust."""

    name: str
    status: str
    value: float | None = None
    age_hours: float | None = None
    max_age_hours: float | None = None
    reasons: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status == OK

    @property
    def reportable(self) -> bool:
        """Suspect data may be shown to the operator, but cannot alone justify an action."""
        return self.status in (OK, SUSPECT)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "value": self.value,
                "age_hours": self.age_hours, "max_age_hours": self.max_age_hours,
                "reasons": list(self.reasons), "usable": self.usable}


@dataclass(frozen=True)
class TrustReport:
    """The data agent's answer: what may be believed, what replaces it, what is missing."""

    as_of: str | None
    sources: dict[str, SourceVerdict]
    primary: str | None
    fallback_mode: bool
    telemetry_missing_fraction: float | None
    reasons: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    suspect_values: tuple[dict, ...] = ()

    @property
    def usable(self) -> bool:
        """A decision may proceed only when at least one quality source stands up."""
        return self.primary is not None

    def verdict(self, name: str) -> SourceVerdict:
        return self.sources[name]

    def refusal_reason(self) -> str | None:
        """What exactly would have to change for a decision to become possible."""
        if self.usable:
            return None
        if self.missing_requirements:
            return "Нет достоверного источника качества. Недостаёт: " + "; ".join(self.missing_requirements)
        return "Нет достоверного источника качества."

    def to_dict(self) -> dict:
        return {"as_of": self.as_of, "usable": self.usable, "primary": self.primary,
                "fallback": self.fallback_mode,
                "telemetry_missing_fraction": self.telemetry_missing_fraction,
                "sources": {k: v.to_dict() for k, v in self.sources.items()},
                "reasons": list(self.reasons),
                "missing_requirements": list(self.missing_requirements),
                "suspect_values": list(self.suspect_values),
                "rule": "ЛИМС выше ПАК по приоритету источника независимо от точности прогноза. "
                        "Источник без подтверждённой пригодности не проходит молча.",
                "refusal_reason": self.refusal_reason()}


def inspect_value(tag: str, value) -> dict | None:
    """Flag a value as worth checking without deciding it is wrong."""
    if value is None or not _finite(value):
        return {"tag": tag, "value": None, "note": "Значение отсутствует или не является числом"}
    if value == PLACEHOLDER_VALUE:
        return {"tag": tag, "value": float(value),
                "note": "Ровно 307: заглушка опроса, по ответу экспертов — выброс (сообщение 582). "
                        "При загрузке источников такие значения заменяются пропуском."}
    if value < 0:
        return {"tag": tag, "value": float(value),
                "note": "Отрицательное значение. Автоматически ошибкой не считается: для вакуума "
                        "и смещения нуля это физически возможно."}
    return None


def _lab_verdict(state: dict, cfg: dict) -> SourceVerdict:
    value = state.get("lab_value")
    age = state.get("lab_age_hours")
    limit = cfg.get("lab_max_age_hours")
    reasons: list[str] = []
    if value is None or not _finite(value):
        return SourceVerdict("ЛИМС", MISSING, None, age, limit,
                             ("Нет доступного лабораторного результата",))
    if not state.get("lab_usable", False):
        reasons.append("Лабораторный результат помечен как непригодный при построении состояния")
    if age is not None and _finite(age) and _finite(limit) and age > limit:
        reasons.append(f"Анализ старше допустимых {limit:g} ч: возраст {age:.1f} ч")
    if value < 0:
        reasons.append("Отрицательная сера в лабораторном результате")
    status = UNUSABLE if reasons else OK
    return SourceVerdict("ЛИМС", status, float(value), age, limit, tuple(reasons))


def _pak_verdict(state: dict, cfg: dict) -> SourceVerdict:
    value = state.get("pak_value")
    age_minutes = state.get("pak_age_minutes")
    age = None if age_minutes is None or not _finite(age_minutes) else age_minutes / 60
    limit_minutes = cfg.get("pak_max_age_minutes")
    limit = None if not _finite(limit_minutes) else limit_minutes / 60
    reasons: list[str] = []
    if value is None or not _finite(value):
        return SourceVerdict("ПАК", MISSING, None, age, limit, ("Нет показаний поточного анализатора",))
    if state.get("pak_frozen"):
        reasons.append("Показание не меняется в течение часа: подозрение на зависание прибора")
    if state.get("pak_conflict"):
        reasons.append("Показание расходится с лабораторным результатом той же пробы")
    if age is not None and limit is not None and age > limit:
        reasons.append(f"Показание старше допустимых {limit_minutes:g} мин: возраст {age * 60:.0f} мин")
    if not state.get("pak_usable", False) and not reasons:
        reasons.append("Показание помечено как непригодное при построении состояния")
    status = UNUSABLE if reasons else OK
    return SourceVerdict("ПАК", status, float(value), age, limit, tuple(reasons))


@dataclass
class DataTrustAgent:
    """Assesses availability, staleness, freezing, contradictions and value admissibility."""

    cfg: dict = field(default_factory=dict)

    #: Telemetry may be incomplete, but not to the point where features stop meaning anything.
    max_missing_fraction: float = 0.1

    def assess(self, state: dict) -> TrustReport:
        cfg = self.cfg
        lab = _lab_verdict(state, cfg)
        pak = _pak_verdict(state, cfg)
        sources = {"ЛИМС": lab, "ПАК": pak}
        reasons: list[str] = []
        missing: list[str] = []
        for verdict in sources.values():
            reasons.extend(f"{verdict.name}: {r}" for r in verdict.reasons)

        missing_fraction = state.get("telemetry_missing_fraction")
        limit = cfg.get("telemetry_max_missing_fraction", self.max_missing_fraction)
        telemetry_ok = (_finite(missing_fraction) and 0 <= missing_fraction <= limit)
        if not telemetry_ok:
            shown = "неизвестна" if not _finite(missing_fraction) else f"{missing_fraction:.1%}"
            reasons.append(f"Телеметрия: доля пропусков {shown} вне допустимых 0–{limit:.1%}")
            missing.append("полная свежая телеметрия за последний срез")

        suspect = tuple(found for found in
                        (inspect_value(tag, value) for tag, value in (state.get("raw_values") or {}).items())
                        if found is not None)

        # Priority is the brief's, not the forecaster's: LIMS outranks PAK even when PAK
        # happens to predict better.
        primary = None
        if telemetry_ok:
            for name in SOURCE_PRIORITY:
                if sources[name].usable:
                    primary = name
                    break
        if primary is None:
            if lab.status == MISSING:
                missing.append("свежий лабораторный анализ серы после гидроочистки")
            if pak.status in (MISSING, UNUSABLE):
                missing.append("исправный поточный анализатор либо подтверждение его показаний")

        # Falling back means the analyzer cannot be relied on, so a model using its
        # features must not be used either.
        fallback_mode = not sources["ПАК"].usable
        return TrustReport(state.get("decision_time"), sources, primary, fallback_mode,
                           float(missing_fraction) if _finite(missing_fraction) else None,
                           tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(missing)), suspect)
