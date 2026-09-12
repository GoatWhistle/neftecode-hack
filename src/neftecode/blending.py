"""Blending three qualities, and what the cetane additive may and may not be credited with.

Sulfur is a mass balance: no reaction happens in a tank, so the blend carries the mass-weighted
sulfur of its components. That is the only one of the three with a defensible exact rule here.

T95 and cetane number are NOT mass-additive in reality. Distillation points and cetane number
blend non-linearly, and the package supplies no blending indices. So each is computed by a
declared scenario rule with its own applicability, and the result says which rule produced it.
Applying the sulfur formula to them silently would be the easy, wrong answer.

Anything unknown stays unknown. A component with no cetane number makes the blend's cetane
number unknown — not "fine", not "the average of the others".
"""
from dataclasses import dataclass
import math

from .scenario import QUALITIES, QUALITY_DIRECTION, Additive, Scenario, Tank

#: How each property is obtained. Reported with every blend so no rule is applied invisibly.
MASS_BALANCE = "mass_balance"
SCENARIO_LINEAR = "scenario_linear_index"
UNKNOWN = "unknown"

#: Properties the cetane additive is allowed to touch. Sulfur is deliberately absent:
#: a cetane improver does not remove sulfur, and the scenario loader refuses to claim it does.
ADDITIVE_MAY_AFFECT = ("cetane_number", "t95_c")


class BlendError(ValueError):
    """Raised when a recipe is impossible or a dose exceeds what the expert allowed."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class BlendResult:
    """Qualities of one blend, each with the rule that produced it."""

    qualities: dict[str, float | None]
    methods: dict[str, str]
    total_mass_t: float
    component_mass_t: dict[str, float]
    additive_mass_t: float = 0.0
    notes: tuple[str, ...] = ()

    def unknown_qualities(self) -> list[str]:
        return [name for name in QUALITIES if self.qualities.get(name) is None]

    def to_dict(self) -> dict:
        return {"qualities": dict(self.qualities), "methods": dict(self.methods),
                "total_mass_t": self.total_mass_t, "component_mass_t": dict(self.component_mass_t),
                "additive_mass_t": self.additive_mass_t, "notes": list(self.notes),
                "unknown_qualities": self.unknown_qualities()}


def check_recipe(recipe: dict[str, float]) -> None:
    """Fractions must be a real composition before anything is computed from them."""
    if not recipe:
        raise BlendError("Рецепт пуст: смешивать нечего")
    for name, fraction in recipe.items():
        if not _finite(fraction):
            raise BlendError(f"Доля компонента {name} должна быть конечным числом")
        if fraction < -1e-9:
            raise BlendError(f"Отрицательная доля компонента {name}: {fraction}")
    total = sum(recipe.values())
    if abs(total - 1.0) > 1e-6:
        raise BlendError(f"Доли компонентов дают {total:.6f}, требуется ровно 1.0")


def mass_balance(recipe: dict[str, float], values: dict[str, float | None]) -> float | None:
    """Mass-weighted average. One unknown component makes the whole result unknown."""
    total = 0.0
    for name, fraction in recipe.items():
        if fraction <= 1e-12:
            continue  # a component not actually used cannot make the blend unknown
        value = values.get(name)
        if value is None or not _finite(value):
            return None
        total += fraction * value
    return total


@dataclass
class Blender:
    """Blends the scenario's tanks, using the scenario's own rules for each property."""

    scenario: Scenario

    def _tank(self, tank_id: str) -> Tank:
        return self.scenario.tank(tank_id)

    def _additive(self) -> Additive | None:
        return self.scenario.additive

    def check_dose(self, dose: float) -> None:
        additive = self._additive()
        if not _finite(dose) or dose < 0:
            raise BlendError(f"Доза присадки должна быть конечной и неотрицательной, получено {dose!r}")
        if dose == 0:
            return
        if additive is None:
            raise BlendError("Сценарий не описывает присадку, но задана ненулевая доза")
        if dose > additive.max_dose_fraction.value + 1e-12:
            raise BlendError(f"Доза присадки {dose:.4f} превышает заданный предел "
                             f"{additive.max_dose_fraction.value:.4f}")

    def blend(self, recipe: dict[str, float], throughput_tph: float, hours: float = 1.0,
              additive_dose: float = 0.0,
              property_overrides: dict[str, dict[str, float | None]] | None = None) -> BlendResult:
        """Blend `throughput_tph` for `hours`, with the additive dosed on the component mass."""
        check_recipe(recipe)
        self.check_dose(additive_dose)
        if not _finite(throughput_tph) or throughput_tph < 0:
            raise BlendError("Выпуск должен быть конечным и неотрицательным")
        if not _finite(hours) or hours < 0:
            raise BlendError("Длительность должна быть конечной и неотрицательной")
        unknown_tanks = [name for name in recipe if recipe[name] > 1e-12
                         and name not in {t.tank_id for t in self.scenario.tanks}]
        if unknown_tanks:
            raise BlendError(f"Рецепт использует не описанные резервуары: {', '.join(unknown_tanks)}")

        component_mass = throughput_tph * hours
        masses = {name: component_mass * fraction for name, fraction in recipe.items()}
        # The dose is a share of the component mass; the additive adds its own mass on top.
        additive_mass = component_mass * additive_dose
        notes: list[str] = []

        overrides = property_overrides or {}
        values = {q: {name: (overrides.get(name, {}).get(q, self._tank(name).property_value(q)))
                         for name in recipe} for q in QUALITIES}
        qualities: dict[str, float | None] = {}
        methods: dict[str, str] = {}

        # Sulfur: a genuine mass balance, diluted by the additive mass that carries none itself.
        sulfur = mass_balance(recipe, values["sulfur_mgkg"])
        if sulfur is None:
            qualities["sulfur_mgkg"], methods["sulfur_mgkg"] = None, UNKNOWN
        else:
            total_mass = component_mass + additive_mass
            qualities["sulfur_mgkg"] = (sulfur * component_mass / total_mass) if total_mass > 0 else sulfur
            methods["sulfur_mgkg"] = MASS_BALANCE
            if additive_mass > 0:
                notes.append("Присадка снижает серу только разбавлением массы; удаление серы "
                             "ей не приписывается.")

        # T95 and cetane number: declared scenario rules, not the sulfur formula.
        for quality in ("t95_c", "cetane_number"):
            blended = mass_balance(recipe, values[quality])
            if blended is None:
                qualities[quality], methods[quality] = None, UNKNOWN
                missing = [n for n in recipe if recipe[n] > 1e-12
                           and self._tank(n).property_value(quality) is None]
                notes.append(f"{quality}: свойство неизвестно у компонентов {', '.join(missing)}; "
                             f"смесь не получает значения и не проходит проверку по умолчанию.")
                continue
            qualities[quality], methods[quality] = blended, SCENARIO_LINEAR
            notes.append(f"{quality} считается линейным сценарным правилом по массовым долям. "
                         f"В действительности этот показатель смешивается нелинейно; индексов "
                         f"смешения в пакете нет, поэтому правило объявлено допущением.")

        # The additive acts only on what the scenario says it acts on.
        additive = self._additive()
        if additive_dose > 0 and additive is not None:
            for quality in additive.affects:
                if quality not in ADDITIVE_MAY_AFFECT:
                    raise BlendError(f"Присадке нельзя приписывать влияние на {quality}")
                gain = additive.cetane_gain_per_dose_pct
                if gain is None:
                    qualities[quality], methods[quality] = None, UNKNOWN
                    notes.append(f"{quality}: зависимость эффекта присадки от дозы не задана, "
                                 f"поэтому результат неизвестен, а не улучшен.")
                    continue
                if qualities.get(quality) is None:
                    continue
                qualities[quality] += gain.value * additive_dose * 100
                methods[quality] = SCENARIO_LINEAR
                notes.append(f"Прирост {quality} от присадки — сценарное допущение "
                             f"({gain.value:g} ед. на 1% дозы); кривая эффекта экспертами не дана.")

        return BlendResult(qualities, methods, component_mass + additive_mass, masses,
                           additive_mass, tuple(dict.fromkeys(notes)))

    def meets_spec(self, result: BlendResult) -> dict[str, dict]:
        """Compare each quality with its limit. Unknown is reported as unknown, never as a pass."""
        checks = {}
        for quality in QUALITIES:
            limit = self.scenario.product.limit_value(quality)
            value = result.qualities.get(quality)
            if limit is None:
                checks[quality] = {"status": "unknown", "value": value, "limit": None,
                                   "reason": f"Предел {quality} не задан ни ТЗ, ни сценарием"}
            elif value is None:
                checks[quality] = {"status": "unknown", "value": None, "limit": limit,
                                   "reason": f"Значение {quality} для смеси неизвестно"}
            else:
                direction = QUALITY_DIRECTION[quality]
                ok = value <= limit + 1e-9 if direction == "max" else value >= limit - 1e-9
                checks[quality] = {
                    "status": "pass" if ok else "fail", "value": value, "limit": limit,
                    "direction": direction,
                    "margin": (limit - value) if direction == "max" else (value - limit),
                    "reason": "" if ok else f"{quality} = {value:.3f} нарушает предел {limit:g}"}
        return checks
