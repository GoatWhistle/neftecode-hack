from dataclasses import dataclass

STATES = ("loading", "error", "decision", "refusal")


class UiError(ValueError):
    pass


STATUS_LABELS = {"hold": "Сохранить режим", "recommend_scenario": "Сценарная рекомендация",
                 "refuse": "Надёжной рекомендации нет"}


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
        return {
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


def error_payload(message: str) -> dict:
    return {"state": "error", "message": message}
