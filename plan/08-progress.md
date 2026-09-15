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
| T60 regression net | готово | a07284c | tests/agentic/test_legacy_baseline.py | 17 новых; полный suite 854 passed |
| T62 порты LLM и response effect | готово | 329037d | application/ports/llm.py, response_effect.py, ports/__init__.py, infrastructure/response/* | tests/agentic/test_ports.py 5; architecture зелёные |
| — `.env` в .gitignore | готово | 0ae092f | .gitignore | найдено при работе: `.env` не игнорировался; в истории git отсутствует |
| T61 экстракция `_search`/`release` | готово | a82c9f3 | application/use_cases/make_decision.py | golden hash без изменений; полный suite 859 passed |
| T63 контракты и бюджет | готово | 5642762 | application/agentic/{__init__,contracts,budget}.py | tests/agentic/test_agent_contracts.py 66 |
| T65 ScriptedLLM/PolicyLLM и сетевой guard | готово | 3000d3a | infrastructure/llm/scripted.py, tests/agentic/conftest.py | tests/agentic/test_scripted.py 4 |
| T64 адаптеры провайдеров | готово (субагент, проверено главным) | см. git log | infrastructure/llm/{__init__,config,errors,openai_compatible,anthropic,factory}.py | test_llm_config 19, test_llm_providers 29; всё tests/agentic 152 passed |

## Нерешённые вопросы

- Условия Z.AI Coding Plan (R10) — риск принят пользователем; live smoke один.
- Offline-требование (R12) — агентный режим по умолчанию выключен.
- Семантика T11/F26 для response layer — ждёт организаторов.

## Заметки

- T64 выполнен субагентом на эксклюзивных файлах. Проверка главным: `Secret` был dataclass — `dataclasses.asdict(settings)` раскрыл бы ключ; переделан в обычный неизменяемый класс + тест.

- `tests/agentic/` без `__init__.py` (как `tests/services/`): имена тестовых модулей должны быть уникальны во всём `tests/`.
- T60: `final_recheck_failed` форсируется подменой `planner.evaluate` на последнем вызове (число вызовов снимается предварительным прогоном).
