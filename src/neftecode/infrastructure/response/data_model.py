"""Эффект температуры входа Р-202 по данным (β на ht.T6) для инструмента агентов `get_response_effect`.

Источник чисел — модель ГО связанного сценария (`binding.response_model` в живом контексте), то есть ровно
то, что уже использует детерминированный контур после `bind_measurements`. Адаптер ничего не оценивает сам:
без живой привязки, вне области отклика или без измерения T6 он отвечает «недоступно» и объясняет почему.
"""
from collections.abc import Mapping
import math


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pair(value) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_finite(v) for v in value)


class DataResponseEffect:
    """ΔS ≈ β·ΔT в конверте исследования; диапазоны — ДИ β и границы следующего полугодия."""

    spec = "config/response_model.json (β на ht.T6, RESPONSE_MODEL_T6.md)"

    def effect(self, context: Mapping[str, object], delta_t_c: float) -> Mapping[str, object]:
        binding = (context or {}).get("binding") or {}
        model = binding.get("response_model") or {}
        base = {"spec": self.spec, "delta_t_c": delta_t_c}
        if not binding:
            return {**base, "available": False,
                    "reason": "Живой привязки к измерениям нет (сценарный запуск): отклик по данным не применяется, "
                              "эффект температуры — только сценарная модель."}
        if model.get("provenance") != "derived" or not _finite(model.get("beta_mgkg_per_c")):
            notes = ((binding.get("measurement_binding") or {}).get("notes") or [])
            return {**base, "available": False,
                    "reason": "Отклик по данным к этому моменту не применён: " + ("; ".join(notes) or
                                                                                "нет измерения T6 или модели отклика")}
        beta = float(model["beta_mgkg_per_c"])
        envelope = float(model.get("envelope_dt_c") or 2.0)
        if abs(delta_t_c) > envelope + 1e-9:
            return {**base, "available": False,
                    "reason": f"|ΔT| больше конверта исследования {envelope:g} °C"}
        out = {**base, "available": True,
               "reference_temp_c": model.get("reference_temp_c"),
               "beta_mgkg_per_c": beta,
               "sulfur_change_mgkg": round(beta * delta_t_c, 4),
               "basis": "ΔS ≈ β·ΔT для серы потока после ГО; β — средний накопленный отклик через 3–8 ч после "
                        "устойчивого шага T6 (ARX по данным 2025 года)",
               "note": "В сценарии ГО эффект начинается через объявленную задержку 2 ч, в исследовании плато — 3–8 ч; "
                       "за горизонт 3 ч эффект может быть меньше полного."}
        if _pair(model.get("beta_ci")):
            out["sulfur_change_ci_mgkg"] = sorted(round(b * delta_t_c, 4) for b in model["beta_ci"])
        if _pair(model.get("weak_strong")):
            out["sulfur_change_next_half_year_mgkg"] = sorted(round(b * delta_t_c, 4) for b in model["weak_strong"])
        return out
