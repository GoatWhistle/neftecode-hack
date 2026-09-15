# 06. Стратегия тестирования

## 1. Принципы

- **0 реальных LLM-вызовов** в unit, contract, integration, regression, agent-loop, repair и provider тестах.
- Все agentic-тесты — в `tests/agentic/`; `tests/agentic/conftest.py` содержит autouse fixture, подменяющую
  `urllib.request.urlopen` и `socket.create_connection` функцией, которая падает с `AssertionError("network call in tests")`.
  Тесты провайдеров явно ставят свой mock поверх неё.
- `infrastructure/llm/factory.py` отказывается создавать `zai/openai/anthropic` клиента, если задан `PYTEST_CURRENT_TEST`
  (второй барьер).
- Итеративный порядок: targeted unit → provider mocks → contracts → regression → существующий suite → FakeLLM E2E →
  один live smoke. Полный suite (~47 с) — после T61, T70, T72 и в T74.

## 2. Уровни

| Уровень | Что | Файлы |
|---|---|---|
| Regression (legacy) | golden sha256 4 сценариев (существующий), статусы/планы/refusal kinds, final_recheck_failed, unknown limit, fragile, DataRejection | `tests/test_architecture_baseline.py`, `tests/agentic/test_legacy_baseline.py` |
| Architecture | слои, запрет «http» в application, Coordinator, flat-модули | `tests/architecture/test_layers.py`, `tests/test_architecture_baseline.py` |
| Unit: contracts | парсеры opinion/final/constraint, диапазоны, обрезка, лишние ключи, типы | `test_agent_contracts.py` (имя `test_contracts.py` уже занято в tests/) |
| Unit: budget | вызовы, шаги, replans, consults, дедлайн (фиктивные часы) | `test_budget.py` |
| Unit: session/tools | margins/utilization/changes против ручного расчёта из gate checks; фильтры; shortlist; кэши; allowlist; обрезка | `test_session_tools.py` |
| Provider (mock HTTP) | формат запросов Z.AI/OpenAI/Anthropic, разбор tool_calls, usage, ошибки, retry, timeout, secret redaction, .env | `test_llm_providers.py`, `test_llm_config.py` |
| Agent loop | final tool, repair, корректирующий вызов, forced final, неизвестный tool, лимиты, LLMError | `test_loop.py` |
| Specialists | разные ситуации → разные последовательности tools (PolicyLLM); grounding; UNKNOWN при сбое | `test_specialists.py` |
| Orchestrator | resolution, override rank, keep_legacy/refuse правила, replan, consults | `test_orchestrator_agent.py` |
| Safety (adversarial) | LLM ACCEPT + Gate FAIL ⇒ FAIL; unknown id; ослабление; мусор; бесконечные tools; исключения; guard | `test_safety.py` |
| Wiring | flag off ⇒ legacy dict и отсутствие клиента; flag on + scripted ⇒ `agentic`; HTTP `/v1/decisions`; explain/Screen | `test_wiring.py` |
| Old vs new | 4 сценария × политики; таблица различий | `test_old_vs_new.py` |
| Demo | `agent-demo` детерминирован (два запуска — одинаковый JSON без latency) | `test_agent_demo.py` |

## 3. FakeLLM

- `ScriptedLLM(responses: list[LLMResponse | Exception])` — строгая очередь; лишний вызов → `AssertionError`.
- `PolicyLLM(policy: Callable[[str role, list messages, list tools], LLMResponse])` — роль определяется по system prompt
  (маркер роли); политика читает последние tool-сообщения (JSON) и решает следующий шаг. Позволяет показать, что путь
  зависит от результатов tools, без сети.
- Helpers: `tool_call(name, **args)`, `text(content)`, `usage(p, c)`.
- Adversarial политики: `select_infeasible`, `select_unknown_id`, `loosen_constraint`, `garbage_json`, `endless_tools`,
  `raise_provider_error(kind)`, `refuse_without_evidence`, `accept_everything`.

## 4. Детерминизм

Agentic-результат со scripted/policy LLM детерминирован; latency в trace исключается из сравнений (или часы
инжектируются). `decision_id` вычисляется до добавления `agentic` и совпадает у одинаковых итоговых планов.

## 5. Один live smoke

- Скрипт `scripts/agent_live_smoke.py` вне pytest (не собирается `testpaths=["tests"]`).
- Режимы: `--dry-run` (по умолчанию) — загружает настройки, проверяет endpoint содержит `/api/coding/`, модель
  `glm-5.3-flash`, ключ присутствует (печатает только `present`), печатает provider/model/base_url/max_calls/scenario;
  сети нет. `--live` — то же + один end-to-end `AgenticMakeDecision.decide` на `baseline` (budget 400) с
  `AGENT_MAX_LLM_CALLS ≤ 12`, `LLM_MAX_RETRIES=0`.
- Условия запуска: T72 зелёный, dry-run успешен, секрет не в выводе.
- Результат: статус, outcome, число вызовов, usage, tools в trace → `artifacts/agent-live-smoke.json` и сводка в
  `plan/08-progress.md`. Повторный live — только по новому прямому поручению пользователя.
