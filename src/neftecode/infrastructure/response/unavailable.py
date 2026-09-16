"""Response effect adapter used until the data-derived response layer is integrated."""
from collections.abc import Mapping

REASON = ("Модель отклика серы на температуру ГО (RESPONSE_MODEL_FINAL.md v3) не встроена: она построена на T11 "
          "как температуре входа реактора и F26 как расходе сырья, а официальный справочник 16.09 называет T11 "
          "температурой на выходе Р-202, F26 — расходом гидроочищенного ДТ; вход реактора — T6, сырьё — F9/F15. "
          "Нужен пересчёт на T6 по решению пользователя.")


class UnavailableResponseEffect:
    """Always answers that the data-derived effect is unavailable; never invents a number."""

    spec = "RESPONSE_MODEL_FINAL.md v3"

    def effect(self, context: Mapping[str, object], delta_t_c: float) -> Mapping[str, object]:
        return {"available": False, "reason": REASON, "spec": self.spec, "delta_t_c": delta_t_c}
