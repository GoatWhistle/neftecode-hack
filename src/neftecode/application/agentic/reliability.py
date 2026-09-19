from dataclasses import dataclass

from .specialist import COMMON_RULES, CONSTRAINT_VOCABULARY, SpecialistAgent
from .tools import RELIABILITY_TOOLS

RELIABILITY_PROMPT = f"""ROLE: reliability
Ты — агент эксплуатационной надёжности советчика для цепочки АВТ → гидроочистка → смешение.
Цель: оценить эксплуатационную разумность и устойчивость плана, уже прошедшего обязательные проверки:
число и величину вмешательств, близость уставок к границам диапазона, загрузку отбора из резервуаров,
траекторию запасов, устойчивость к отклонениям модели, необходимость изменения режима и наличие альтернатив
с меньшим вмешательством. Жёсткие ограничения проверяет Gate, а не ты: check_hard_constraints только читает его итог.
Ограничения оборудования заданы сценарием и не являются оценкой реального ресурса.
{COMMON_RULES}{CONSTRAINT_VOCABULARY}
"""


@dataclass(frozen=True)
class ReliabilityAgent(SpecialistAgent):
    role: str = "reliability"
    system_prompt: str = RELIABILITY_PROMPT
    allowlist: tuple[str, ...] = RELIABILITY_TOOLS
