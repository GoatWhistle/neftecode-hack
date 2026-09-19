# 08. Прогресс

## Итог на текущий момент

Фазы 2–7 выполнены: план, регрессионная сетка, провайдеры, контракты, специалисты, оркестратор, подключение за флагом.

## Базовая линия (2026-09-16, HEAD 1c795ca)

- `pytest -q`: 1263 теста в наборе (18.09.2026).
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
| T71 детерминированный demo trace | готово | 64f7d15 | composition/commands/agentic.py, presentation/reports/agent_trace.py, presentation/cli.py, dispatcher.py, orchestrator.py (событие consult) | test_agent_demo 2; `neftecode agent-demo` пишет artifacts/agent-demo.{json,md} (artifacts не коммитятся) |
| T72 old vs new и fuzz | готово | 2bad66d | tests/agentic/test_old_vs_new.py | 41 тест; полный suite 1100 passed, 88 с |

### Old vs new (budget 400, без state)

| Сценарий | legacy | agentic: demo-политика | agentic: сбой провайдера | agentic: 8 случайных политик |
|---|---|---|---|---|
| baseline | hold | hold (confirmed_legacy) | hold (fallback) | hold ×8 |
| sour_crude | recommend c0025, 180 т, хрупкий 6/8 | recommend c0030, 150 т, хрупкий 7/8, запас серы ≥ 0.398 | как legacy | recommend или refuse (agent_rejected) |
| ample_reserve | recommend c0029 | recommend c0158 | как legacy | recommend или refuse |
| no_feasible | refuse no_feasible_plan | refuse (confirmed_legacy) | как legacy | refuse ×8 |

Исходы 32 случайных прогонов: confirmed_legacy 12, fallback 16 (selection_not_allowed 7, refuse_without_evidence 6, нет finalize 3),
refused 3, selected 1. Во всех: выпущенный план проходит свежий Gate, `unexpected_error` нет, вызовов LLM ≤ 12, при fallback
решение совпадает с legacy байт-в-байт.
| T73 live smoke (два запуска) | выполнен | см. git log | scripts/agent_live_smoke.py, loop.py (код ошибки в trace) | dry-run: provider zai, model glm-5.3-flash, base_url .../api/coding/paas/v4, ключ present. Запуск 1: ошибка `quota`, 1 вызов, legacy hold. Запуск 2 (разрешён пользователем): модель выбирала инструменты, QualityAgent ACCEPT с обоснованием, 7 вызовов, 25.6k токенов, исчерпан бюджет времени → legacy hold, Gate PASS |

### Итог live smoke (2026-09-16)

**Запуск 1.** Провайдер отклонил первый же запрос ошибкой класса `quota`. Слой отработал как задумано: один вызов,
без повторов, детерминированный hold (Gate PASS, устойчивость 8 из 8). Точный код не сохранился — запись кода ошибки
в trace добавлена после этого прогона.

**Запуск 2** (по отдельному разрешению пользователя, сценарий baseline, `AGENT_MAX_LLM_CALLS=8`). Модель работала:
- оркестратор сам выбрал `ask_quality_agent` и сформулировал focus (сравнить hold с c0126/c0133);
- QualityAgent вызвал `compare_candidates`, `get_quality_margins`, `get_lookahead`, `get_tank_projection`,
  `get_robustness` и вернул ACCEPT с кодами `margins_superior`, `robustness_held`, `lookahead_clear`,
  `cost_delta_small`, `data_trust_low` — числа в обосновании совпадают с выдачей инструментов;
- ReliabilityAgent вызвал `compare_operating_load`, `get_robustness` (второй запуск отклонён лимитом),
  `get_setpoint_changes` ×2, `get_lookahead` и не успел до `submit_opinion`;
- 7 вызовов LLM, latency 10–45 с, usage 18 768 + 6 818 = 25 586 токенов (≈10 кредитов Coding Plan);
- общий бюджет времени 180 с исчерпан → `outcome=fallback`, решение — детерминированный hold, Gate PASS.

Выводы: (1) агент действительно выбирает инструменты по ситуации и обосновывает вердикт их результатами;
(2) исходные таймауты были малы — подняты до 600 с общего и 120 с на запрос; (3) страховка сработала:
исчерпание бюджета не портит решение. Полного живого прохода до `finalize` пока нет.

## Агенты включены всегда (2026-09-16, по указанию пользователя)

- `agentic_enabled`: слой включён, если переменная не равна `0/false/no/off`.
- `tests/conftest.py` фиксирует `AGENTIC_DECISION_ENABLED=0` для набора тестов (эталонные решения, без обращения к модели); агентные тесты собирают фабрики явно; добавлен тест «включено по умолчанию».
- Gateway ждёт decision до 660 с (`NEFTECODE_GATEWAY_DECISION_TIMEOUT_S`), прочие вызовы — 10 с.
- Документация: README, `context/architecture.md`, `context/state.md`, `context/data-flow.html`, plan/01–03, 07.
- 1104 passed. Живые вызовы модели при этом не выполнялись.

## Материалы 15–16 сентября (2026-09-17)

T75–T82 (`context/backlog.md`): 307 — выброс; пороги доверия из данных; официальные формулы ВАК и справочник тегов;
пределы продукта и запас по сере; провайдер `local` как вариант, по умолчанию Z.AI. Для агентов важно: контекст
агента качества содержит `sulfur_operating_margin_mgkg`, демо-политика берёт порог оттуда. 1263 теста в наборе.

## Аудит T74 (2026-09-16, выполнен главным агентом; субагент-аудитор остановлен лимитом сессии)

Проверено по инвариантам `plan/02-compatibility-contract.md`:

| # | Инвариант | Результат |
|---|---|---|
| I1 | Flag off ⇒ прежний dict и 20 ключей | `test_four_scenario_outputs_are_frozen` зелёный; CLI `screen` даёт decision_id d6a1ab7f26398791 |
| I2 | Gate — единственный источник допустимости | `test_safety.py` (выбор недопустимого, неизвестного, ослабление) + fuzz 32 прогона |
| I3 | Guard переоценивает свежим планировщиком | `_guard` + тест с подменой `PlanOperation` |
| I4 | Общий `release` | экстракция T61 под golden hash |
| I5–I7 | Отказ по данным без вызовов; отказ no_feasible; fallback на любой сбой | тесты + живой прогон (реальные quota и timeout дали legacy) |
| I8 | Ограничения только ужесточают | закрытый словарь, `parse_constraints`, диапазоны; нет tool, меняющего сценарий или пределы |
| I9 | Выбор — `rank()`; LLM не переопределяет | `llm_choice_overridden` |
| I10 | 0 сетевых вызовов в тестах | autouse guard + отказ factory под pytest |
| I11 | Секрет не утекает | `Secret` (не dataclass), redaction ошибок, тесты; `git log --all -- .env` пуст; `.env` в .gitignore |
| I12 | Статусы и UI | `Screen`/`explain` на agentic-решении, kind `agent_rejected` |
| I13 | Слои | architecture tests зелёные; в `application` нет запрещённых подстрок |
| I14 | Бюджеты | общий `AgentBudget` у сессии и циклов; живой прогон остановлен бюджетом времени |

Разобранные риски реализации: кэши сессии (`_passes`, `_margins`, `_lookahead`, `_robustness`) привязаны к неизменяемым
`Evaluation`, поэтому не устаревают при новых ограничениях; `allowed_ids()` пересчитывается при каждом обращении;
`release` получает только допустимое множество, поэтому упреждение не может переключиться на запрещённый план;
идентификаторы новых планов не пересекаются с уже оценёнными; исключение legacy-контура (`AgentError`) намеренно
не перехватывается — это прежнее поведение.

Изменения в legacy-коде (14 файлов): экстракция `_search`/`release` и три публичные обёртки в `make_decision.py`,
необязательные `decision_factory` в `get_live_advice.py`, `advisor.py`, `decision_service.py`, фабрика в composition,
новый kind отказа в `explain.py`, команда `agent-demo` в CLI и dispatcher. Математика, коэффициенты, Gate, ranking,
robustness, DataTrust и response-model research не тронуты.

## Нерешённые вопросы

- Условия Z.AI Coding Plan (R10) — риск принят пользователем. Первый live отклонён как `quota` (вероятно окно лимита 5 ч), второй прошёл.
- Полный живой цикл до `finalize` не наблюдался: нужен ещё один запуск с новыми таймаутами — только по отдельному поручению.
- Offline-требование (R12) — с 16.09 агенты включены всегда; в закрытой сети нужна локальная модель или явное `AGENTIC_DECISION_ENABLED=0`.
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
