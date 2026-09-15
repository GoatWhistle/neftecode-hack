# 08. Прогресс

## Итог на текущий момент

Фазы 2–3 в работе: план готов, регрессионная сетка T60 готова. Production-код не менялся.

## Базовая линия (2026-09-16, HEAD 1c795ca)

- `pytest -q`: 837 passed, 47 с.
- Решения budget 400 без state: baseline hold (93 feasible из 200), sour_crude recommend c0025 fragile (2 из 200),
  ample_reserve recommend c0029 (42 из 200), no_feasible refuse no_feasible_plan (0 из 200); ~0.1 с на решение.

## Выполненные задачи

| Задача | Статус | Коммит | Изменённые файлы | Тесты |
|---|---|---|---|---|
| T59 план | готово | 5f534cc | plan/00–08, context/backlog.md, context/state.md | — |
| T60 regression net | готово | см. git log | tests/agentic/test_legacy_baseline.py | 17 новых; полный suite 854 passed |

## Нерешённые вопросы

- Условия Z.AI Coding Plan (R10) — риск принят пользователем; live smoke один.
- Offline-требование (R12) — агентный режим по умолчанию выключен.
- Семантика T11/F26 для response layer — ждёт организаторов.

## Заметки

- `tests/agentic/` без `__init__.py` (как `tests/services/`): имена тестовых модулей должны быть уникальны во всём `tests/`.
- T60: `final_recheck_failed` форсируется подменой `planner.evaluate` на последнем вызове (число вызовов снимается предварительным прогоном).
