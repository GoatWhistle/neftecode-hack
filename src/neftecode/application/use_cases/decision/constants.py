from dataclasses import dataclass, field

MAX_ROUNDS = 3

LOOKAHEAD_CANDIDATES = 40

VETO_FAMILIES = {
    "outflow": "снизить отбор из резервуара",
    "inventory": "уменьшить расход запаса",
    "quality": "усилить качество смеси",
    "control": "остаться в диапазоне уставок",
    "additive": "снизить дозу присадки",
    "model": "остаться в области применимости модели",
}


class AgentError(RuntimeError):
    pass


@dataclass
class SearchOutcome:

    selected: dict | None
    selected_plan: object | None
    feasible: list
    by_id: dict
    rounds: list[dict]
    evaluated: int
    last_result: dict | None
    examined: list = field(default_factory=list)
    examined_by_id: dict = field(default_factory=dict)
    seen_content: set[str] = field(default_factory=set)
    forbidden: frozenset[str] = frozenset()
    computation_errors: list[dict] = field(default_factory=list)
