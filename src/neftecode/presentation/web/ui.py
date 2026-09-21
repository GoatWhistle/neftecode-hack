from dataclasses import dataclass

STATES = ("loading", "error", "decision", "refusal")


class UiError(ValueError):
    pass


STATUS_LABELS = {"hold": "Сохранить режим", "recommend_scenario": "Сценарная рекомендация",
                 "refuse": "Надёжной рекомендации нет"}

# Без агентного слоя (AGENTIC_DECISION_ENABLED=0) решение отдаёт детерминированное ядро и ключа
# decision["agentic"] в нём нет вовсе. Сам decision не трогаем — он обязан совпадать с ядром побитово
# (test_flag_off_demo_decision_is_byte_identical_to_legacy), поэтому явное состояние этапа агентов
# кладётся рядом, на уровень экрана. Когда агенты работали, поля нет: их состояние — decision["agentic"].
AGENTS_SKIPPED = {"mode": "disabled", "outcome": "skipped", "reason": "agents_disabled",
                  "note": "Агентный слой не участвовал (выключен, AGENTIC_DECISION_ENABLED=0): "
                          "решение принял детерминированный код, LLM не вызывалась"}


def agentic_state(decision: dict) -> dict | None:
    return None if decision.get("agentic") is not None else dict(AGENTS_SKIPPED)


@dataclass
class Screen:
    decision: dict
    explanation: dict
    inventories: dict | None = None
    sources: list | None = None
    rule_origin: str | None = None
    state_origin: str | None = None
    decision_time: str | None = None
    forecast: dict | None = None
    forecast_used: bool | None = None
    title: str = "Советчик оператору цепочки АВТ → гидроочистка → смешение"

    def payload(self) -> dict:
        status = self.decision.get("status")
        if status not in STATUS_LABELS:
            raise UiError(f"Неизвестный статус решения: {status}")
        payload = {
            "state": "refusal" if status == "refuse" else "decision",
            "title": self.title,
            "status_label": STATUS_LABELS[status],
            "decision": self.decision,
            "explanation": self.explanation,
            "inventories": self.inventories or {},
            "sources": self.sources or [],
            "rule_origin": self.rule_origin,
            "state_origin": self.state_origin,
            "decision_time": self.decision_time,
            "forecast": self.forecast,
            "forecast_used": self.forecast_used,
        }
        state = agentic_state(self.decision)
        if state is not None:
            payload["agentic_state"] = state
        return payload


def error_payload(message: str) -> dict:
    return {"state": "error", "message": message}
