# 08. Прогресс

## Итог на текущий момент

Фазы 2–7 выполнены: план, регрессионная сетка, провайдеры, контракты, специалисты, оркестратор, подключение за флагом.

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
| T64 адаптеры провайдеров | готово (субагент, проверено главным) | dc85498 | infrastructure/llm/{__init__,config,errors,openai_compatible,anthropic,factory}.py | test_llm_config 19, test_llm_providers 29; всё tests/agentic 152 passed |
| T66 сессия и детерминированные tools | готово | c58d157 | application/agentic/{session,tools,context}.py, make_decision.py (обёртки) | test_session_tools 14; tests/agentic 166 passed; golden без изменений |
| T67 bounded tool loop | готово | c6c6908 | application/agentic/loop.py | test_loop 11 |
| T68 QualityAgent и ReliabilityAgent | готово | fcd88d5 | application/agentic/{specialist,quality,reliability}.py | test_specialists 8: разные пути tools в разных ситуациях (PolicyLLM) |
| T69 OrchestratorAgent и AgenticMakeDecision | готово | f75079d | application/agentic/{orchestrator,decision}.py, infrastructure/llm/demo_policy.py | test_orchestrator_agent 7, test_safety 32; tests/agentic 225 passed |
| T70 подключение за флагом | готово | 2340e62 | infrastructure/agentic/*, composition/decision.py, commands/{screens,live}.py, get_live_advice.py (поле decision_factory), live/advisor.py, services/decision_service.py, services/explain.py (agent_rejected) | test_wiring 10; полный suite 1057 passed; CLI screen: флаг выкл. — decision_id d6a1ab7f26398791 (как legacy), флаг вкл. + scripted — c0030, outcome selected |
| T71 детерминированный demo trace | готово | см. git log | composition/commands/agentic.py, presentation/reports/agent_trace.py, presentation/cli.py, dispatcher.py, orchestrator.py (событие consult) | test_agent_demo 2; `neftecode agent-demo` пишет artifacts/agent-demo.{json,md} (artifacts не коммитятся) |

## Нерешённые вопросы

- Условия Z.AI Coding Plan (R10) — риск принят пользователем; live smoke один.
- Offline-требование (R12) — агентный режим по умолчанию выключен.
- Семантика T11/F26 для response layer — ждёт организаторов.

## Заметки

- T70: `AGENTIC_DECISION_ENABLED` читается только из окружения процесса; `.env` — только настройки провайдера и лимиты при включённом флаге. `DecisionService()` без фабрики остаётся legacy; `main()` передаёт фабрику из окружения. Replay и benchmark не переключаются.

- T69, demo-политика (не LLM) на сценариях, budget 400:
  | Сценарий | legacy | agentic | outcome | вызовы (orch/quality/reliability) | путь |
  |---|---|---|---|---|---|
  | baseline | hold | hold | confirmed_legacy | 3/2/2 | quality: margins → ACCEPT; reliability: setpoint_changes → ACCEPT |
  | sour_crude | recommend c0025 180 т | recommend c0030 150 т | selected | 5/3/3 | quality: margins → forecast+tank → REVISE(min_quality_margin) → search → rank → reliability: changes → robustness |
  | ample_reserve | recommend c0029 | recommend c0158 | selected | 5/3/3 | как sour_crude |
  | no_feasible | refuse | refuse | confirmed_legacy | 3/0/0 | search → rank (пусто) → keep_legacy |
- AgenticMakeDecision запускает `_search` второй раз (детерминированно, ~0.1 с) вместо изменения `decide`: legacy остаётся нетронутым.
- Порядок событий в trace — по завершении: события специалиста идут раньше события `ask_*_agent` оркестратора.

- T68: сессия и цикл обязаны делить один `AgentBudget` (лимит robustness считается в сессии, вызовы LLM — в цикле).

- T66: `require_not_fragile` проверяет устойчивость только у первых `max_candidates` допустимых (порядок: legacy, hold, ключ ранжирования), `min_hours_to_violation` — у первых 40; остальные исключаются (консервативно). Сценарная оценка эффекта температуры ищет уже оценённый постоянный план с тем же рецептом и выпуском.

- T64 выполнен субагентом на эксклюзивных файлах. Проверка главным: `Secret` был dataclass — `dataclasses.asdict(settings)` раскрыл бы ключ; переделан в обычный неизменяемый класс + тест.

- `tests/agentic/` без `__init__.py` (как `tests/services/`): имена тестовых модулей должны быть уникальны во всём `tests/`.
- T60: `final_recheck_failed` форсируется подменой `planner.evaluate` на последнем вызове (число вызовов снимается предварительным прогоном).
