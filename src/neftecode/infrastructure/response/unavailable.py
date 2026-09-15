"""Response effect adapter used until the data-derived response layer is integrated."""
from collections.abc import Mapping

REASON = ("Модель отклика серы на температуру ГО (RESPONSE_MODEL_FINAL.md v3) не встроена: семантика тегов "
          "T11 (температура входа реактора) и F26 (объёмный расход сырья) ждёт подтверждения организаторов.")


class UnavailableResponseEffect:
    """Always answers that the data-derived effect is unavailable; never invents a number."""

    spec = "RESPONSE_MODEL_FINAL.md v3"

    def effect(self, context: Mapping[str, object], delta_t_c: float) -> Mapping[str, object]:
        return {"available": False, "reason": REASON, "spec": self.spec, "delta_t_c": delta_t_c}
