import math

LOOKAHEAD_CONSTRAINT_CAP = 40


class SessionError(ValueError):
    pass


def finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def rounded(value, digits: int = 4):
    return round(value, digits) if finite(value) else value
