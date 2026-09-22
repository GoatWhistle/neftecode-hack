from datetime import datetime
import re


class HistoryError(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code


def local_moment(at: str) -> datetime:
    try:
        if not isinstance(at, str) or "T" not in at and " " not in at:
            raise ValueError
        when = datetime.fromisoformat(at)
    except (TypeError, ValueError) as exc:
        raise HistoryError("invalid_at", "Нужны дата и время в формате ISO, например 2026-07-24T03:07:00") from exc
    if when.tzinfo is not None:
        raise HistoryError("unknown_timezone", "Укажите местное время исходных данных без Z/offset: часовой пояс поставки неизвестен")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?", at):
        raise HistoryError("invalid_at", "Время ISO: точность до микросекунд, без скрытого округления")
    return when
