# 05. Задачи реализации

Правила: только `main`; одна задача — один коммит от текущего Git-пользователя, без `Co-authored-by` и AI-подписей;
push не делать; после каждой задачи обновлять `plan/08-progress.md`, статус в `context/backlog.md` и `context/state.md`.
Перед коммитом каждой задачи, меняющей `src`: `pytest tests/test_architecture_baseline.py tests/architecture -q` + targeted.
Полный suite — после T61, T70, T72.

Статусы: `[ ]` не начато, `[~]` в работе, `[x]` готово.

## Фаза 2 — план

### [x] T59. Документы plan/00–08
- Цель: план, по которому можно продолжить без разговора.
- Файлы: `plan/*.md`, `context/backlog.md`, `context/state.md`.
- Зависимости: чтение кода и документации Z.AI.
- Готово: все 9 документов заполнены; backlog содержит T59–T74.
- Коммит: `docs: спланировать слой LLM-агентов поверх детерминированного ядра`.

## Фаза 3 — регрессионная сеть

### [x] T60. Зафиксировать поведение legacy
- Цель: сетка до любых изменений src.
- Файлы: `tests/agentic/__init__.py`, `tests/agentic/test_legacy_baseline.py`.
- Зависимости: T59.
- Содержание: для 4 сценариев — status, plan_id, refusal.kind, production_t, fragile, lookahead.switched, число раундов
  и evaluated, `decision_id`; HOLD (baseline); RECOMMEND (sour_crude c0025, ample_reserve c0029); REFUSE data через state
  (lab/pak недоступны) и через `DataRejection`; REFUSE no_feasible; **final_recheck_failed** (подмена `planner.evaluate` —
  infeasible только на финальном вызове); unknown limit (T95 None → REFUSE); fragile robustness (sour_crude, reason
  содержит «надёжным не считается»); fallback forecast (ссылка на существующий test_live).
- Готово: новые тесты зелёные на HEAD без изменений src; полный suite зелёный.
- Коммит: `test: зафиксировать поведение детерминированного контура решения`.

### [x] T61. Экстракция `_search` и `release` в MakeDecision
- Цель: переиспользуемые детерминированные этапы без изменения поведения.
- Файлы: `src/neftecode/application/use_cases/make_decision.py`.
- Зависимости: T60.
- Содержание: `SearchOutcome` (selected, selected_plan, feasible, evaluations, by_id, rounds, evaluated, last_result,
  budget); `_search(budget, confirmed, initial_tanks, current_operation) -> SearchOutcome`;
  `release(outcome_or_parts, trace, confirmed, initial_tanks, current_operation, raw_scenario, budget) -> dict`.
  Тексты, порядок trace, константы — без изменений.
- Готово: golden hash, T60 и полный suite зелёные.
- Коммит: `refactor: выделить поиск и выпуск решения в MakeDecision`.

## Фаза 4 — провайдеры и контракты

### [x] T62. Порты LLM и response effect
- Файлы: `application/ports/llm.py`, `application/ports/response_effect.py`, `application/ports/__init__.py`,
  `infrastructure/response/__init__.py`, `infrastructure/response/unavailable.py`, `tests/agentic/test_ports.py`.
- Зависимости: T60 (порядок изменён: порты не трогают legacy, выполнены до T61, чтобы адаптеры T64 шли параллельно).
- Готово: dataclass-валидация сообщений; `UnavailableResponseEffect` возвращает `available=false` с причиной про T11/F26;
  layer tests зелёные (нет «http» в application).
- Коммит: `feat: добавить порты LLM и эффекта отклика`.

### [x] T63. Контракты агентов и строгие парсеры
- Файлы: `application/agentic/__init__.py`, `contracts.py`, `budget.py`, `tests/agentic/test_agent_contracts.py`, `test_budget.py`.
- Зависимости: T62.
- Готово: QualityOpinion/ReliabilityOpinion/OrchestratorFinal/AgentConstraint/AgentSettings/AgentTraceEvent;
  тесты на валидный JSON, лишние ключи, неверные типы/перечисления, диапазоны ограничений, обрезку строк, пустые списки,
  NaN/inf, bool вместо int; `AgentBudget` — вызовы, шаги, replans, consults, дедлайн с инжектируемыми часами.
- Коммит: `feat: описать контракты агентов и бюджеты`.

### [ ] T64. Адаптеры провайдеров с mock HTTP
- Файлы: `infrastructure/llm/__init__.py`, `config.py`, `errors.py`, `openai_compatible.py`, `anthropic.py`, `factory.py`,
  `tests/agentic/test_llm_config.py`, `test_llm_providers.py`.
- Зависимости: T62.
- Готово: запрос Z.AI (URL `…/coding/paas/v4/chat/completions`, Bearer, tools, `tool_choice:auto`), OpenAI, Anthropic
  (`/v1/messages`, x-api-key, tool_use/tool_result) — проверены на подменённом `urllib.request.urlopen`; маппинг ошибок
  (таблица 03 §2.1); retry ≤ 1 только retryable; timeout; `reasoning_content` отброшен; `.env` парсер и aliases
  `ZAI_API_KEY/TOKEN/token`; защита от General endpoint; `Secret` не утекает в repr/исключения; factory отказывает под pytest
  для не-scripted провайдеров.
- Коммит: `feat: добавить адаптеры Z.AI, OpenAI и Anthropic`.

### [ ] T65. ScriptedLLM, PolicyLLM и сетевой guard тестов
- Файлы: `infrastructure/llm/scripted.py`, `tests/agentic/conftest.py`, `tests/agentic/test_scripted.py`.
- Зависимости: T62.
- Готово: autouse fixture делает `urllib.request.urlopen` и `socket.create_connection` падающими во всех `tests/agentic`;
  ScriptedLLM выдаёт ответы по очереди и падает при исчерпании; PolicyLLM вызывает функцию политики.
- Коммит: `test: добавить детерминированные LLM-заглушки и запрет сети`.

## Фаза 5 — специалисты

### [ ] T66. DecisionSession и детерминированные tools
- Файлы: `application/agentic/session.py`, `context.py`, `tools.py`, `tests/agentic/test_session_tools.py`.
- Зависимости: T61, T63.
- Готово: сессия строится из `SearchOutcome`; margins/utilization/changes считаются из gate checks и совпадают с ручным
  расчётом; фильтры ограничений; shortlist детерминирован (legacy selected, hold, далее по `Evaluation.key()`);
  `search_candidates` оценивает только неисследованные планы в пределах бюджета; кэши lookahead/robustness и лимит;
  allowlist по ролям; обрезка результата; исключение tool → `{"error"}`; контекст ≤ лимита символов.
- Коммит: `feat: дать агентам детерминированные инструменты`.

### [ ] T67. Bounded tool loop
- Файлы: `application/agentic/loop.py`, `tests/agentic/test_loop.py`.
- Зависимости: T63, T65, T66.
- Готово: финал через final tool; repair текста; один корректирующий вызов; неизвестный/запрещённый tool; лимит tool_calls
  на ответ; forced final на последнем вызове; BudgetExhausted; LLMError; trace событий; ≤ max_calls вызовов.
- Коммит: `feat: добавить ограниченный цикл вызова инструментов`.

### [ ] T68. QualityAgent и ReliabilityAgent
- Файлы: `application/agentic/quality.py`, `reliability.py`, `tests/agentic/test_specialists.py`.
- Зависимости: T67.
- Готово: system prompts; opinion с grounding-правилами; PolicyLLM в двух ситуациях (маленький запас серы vs большой;
  переходный план с 2 изменениями vs hold) вызывает разные последовательности tools; ошибки → UNKNOWN.
- Коммит: `feat: добавить агентов качества и надёжности`.

## Фаза 6 — оркестратор

### [ ] T69. OrchestratorAgent и AgenticMakeDecision
- Файлы: `application/agentic/orchestrator.py`, `decision.py`, `tests/agentic/test_orchestrator_agent.py`,
  `tests/agentic/test_safety.py`.
- Зависимости: T68.
- Готово: resolution по 01 §6; guard; fallback на каждый класс сбоя; adversarial PolicyLLM (выбор infeasible, unknown id,
  ослабление ограничения, refuse без оснований, бесконечные tools, мусорный JSON, исключение провайдера) никогда не даёт
  план без Gate PASS; data refusal — 0 вызовов LLM; `agentic` добавляется после `decision_id`.
- Коммит: `feat: добавить оркестратора агентов поверх детерминированного контура`.

## Фаза 7 — интеграция

### [ ] T70. Wiring за флагом
- Файлы: `infrastructure/agentic/__init__.py`, `infrastructure/agentic/factory.py`, `composition/decision.py`,
  `composition/commands/screens.py`, `composition/commands/live.py`, `infrastructure/live/advisor.py`
  (передача фабрики), `application/use_cases/get_live_advice.py` (поле `decision_factory`), `services/decision_service.py`,
  `application/services/explain.py` (kind `agent_rejected`), `tests/agentic/test_wiring.py`.
- Зависимости: T69.
- Готово: flag off — golden/весь suite без изменений, LLM-клиент не создаётся, `.env` не читается; flag on +
  `LLM_PROVIDER=scripted` — demo/screen/`/v1/decisions` возвращают `agentic`; UI `Screen` и `explain` принимают dict.
- Коммит: `feat: подключить агентный режим за флагом`.

### [ ] T71. Детерминированный demo trace
- Файлы: `infrastructure/llm/scripted.py` (политика демо), `presentation/cli.py` + `composition/commands/dispatcher.py` +
  `composition/commands/agentic.py` (команда `agent-demo`), `tests/agentic/test_agent_demo.py`.
- Зависимости: T70.
- Готово: `neftecode agent-demo --out artifacts` пишет `agent-demo.json` и `agent-demo.md` для baseline и sour_crude;
  пути агентов различаются; файл явно помечен «scripted policy, не LLM».
- Коммит: `feat: добавить детерминированную демонстрацию агентного режима`.

## Фаза 8 — тесты

### [ ] T72. Old vs new на сценариях и полный suite
- Файлы: `tests/agentic/test_old_vs_new.py`, `plan/08-progress.md`.
- Зависимости: T71.
- Готово: для 4 сценариев × набор политик (accept, veto, constraint, garbage, provider error): agentic не выдаёт HOLD/
  RECOMMEND там, где legacy REFUSE по Gate/данным; выбранный план всегда Gate PASS; таблица old vs new в progress.
- Коммит: `test: сравнить агентный и детерминированный режимы`.

## Фаза 9 — live

### [ ] T73. Один live smoke GLM-5.3-Flash
- Файлы: `scripts/agent_live_smoke.py`, `artifacts/agent-live-smoke.json` (не коммитится, artifacts в .gitignore),
  `plan/08-progress.md`.
- Зависимости: T72 зелёный; endpoint и модель подтверждены (03); ключ в env; dry-run (`--dry-run`: печать конфигурации без
  сети) выполнен.
- Готово: перед запуском напечатаны provider, model, base_url, max_calls, scenario id (без ключа); ровно один запуск
  `--live`; результат и usage записаны; при сбое — разбор локально, без повторного live.
- Коммит: `docs: зафиксировать живую проверку агентного режима`.

## Фаза 10 — аудит

### [ ] T74. Аудит, документация, итог
- Файлы: `README.md`, `context/architecture.md`, `context/state.md`, `plan/08-progress.md`.
- Зависимости: T73.
- Готово: `git diff 1c795ca..HEAD --stat` просмотрен; поиск секрета в tracked-файлах (по имени переменных, без значения);
  `git check-ignore .env`; compat-инварианты 02 перепроверены; независимый read-only ревью субагентом; README/architecture
  описывают агентный режим честно (scripted ≠ LLM; live — один smoke).
- Коммит: `docs: описать агентный режим и итог проверки`.

## Субагенты

| Субагент | Задача | Файлы (эксклюзивно) | Проверка главным |
|---|---|---|---|
| A | T64 провайдеры | `infrastructure/llm/{config,errors,openai_compatible,anthropic,factory}.py`, их тесты | diff, тесты, grep секретов |
| B | T60 regression | `tests/agentic/test_legacy_baseline.py` | запуск тестов на HEAD |
| C | T74 независимый аудит безопасности (read-only) | — | сверка находок с кодом |

T61, T63, T66–T70 делает главный агент: общие файлы ядра, высокая связность.
