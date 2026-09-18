# 02. Контракт совместимости

## 1. Что нельзя менять

- Математику и коэффициенты: `domain/production/*` (ChainModel, Blender, InventoryLedger, Economics), `infrastructure/ml/*`
  (forecast, выбор модели, интервалы), `bind_forecast`/`estimate_tank_sulfur`/`frozen_analyser_hold`.
- `application/services/trust.py` (DataTrust) — правила, пороги, отказ.
- `domain/advisory/gate.py` — набор проверок, статусы, `feasible = all pass`, `unknown` блокирует.
- `domain/advisory/optimizer.py` — `CandidateGenerator`, `rank`, `RANKING`, `min_useful_gain`.
- `evaluation/robustness.py` — перечень возмущений, `FRAGILE_BELOW`, семантика fragile (предупреждение, не отказ).
- `MakeDecision`: `MAX_ROUNDS`, `LOOKAHEAD_CANDIDATES`, veto families, тексты reason, порядок trace, `_finish`, `decision_id`.
- Response-model research (`RESPONSE_MODEL_FINAL.md`, `context/response-research/**`): не переисследовать, не переобучать, β не менять.
- Сценарии `config/scenarios/*.json`, `config/parameters.json`, `config/experiment.json`.
- CLI команды и флаги, HTTP маршруты и конверты `contract_version: v1`.

Допустимые изменения legacy-файлов: behaviour-preserving экстракция методов `MakeDecision._search` и
`MakeDecision.release`, новое необязательное поле `GetLiveAdvice.decision_factory` (default — текущее поведение),
необязательный параметр фабрики в composition/services.

## 2. Инварианты

| # | Инвариант | Как проверяется |
|---|---|---|
| I1 | Явно выключенный флаг ⇒ decision dict 4 сценариев байт-в-байт прежний (sha256) и ровно 20 ключей; набор тестов фиксирует `AGENTIC_DECISION_ENABLED=0` в `tests/conftest.py` | `tests/test_architecture_baseline.py` |
| I2 | Gate — единственный authoritative механизм допустимости; LLM ACCEPT + Gate FAIL ⇒ FAIL | `tests/agentic/test_safety.py` (adversarial FakeLLM) |
| I3 | HOLD/RECOMMEND в agentic ⇒ выбранный план проходит `check_plan` при повторной переоценке | guard в `AgenticMakeDecision` + тест |
| I4 | Final recheck, look-ahead, robustness — тот же код `release` для обоих путей | экстракция + golden |
| I5 | Legacy REFUSE по данным ⇒ agentic REFUSE по данным без вызовов LLM | тест, счётчик вызовов = 0 |
| I6 | Legacy REFUSE no_feasible ⇒ agentic не выдаёт план, не прошедший Gate | тест |
| I7 | Любой сбой LLM (timeout, provider error, malformed, budget) ⇒ legacy-результат + `agentic.outcome=fallback` | тесты loop/decision |
| I8 | LLM-ограничения только сужают множество; пределы сценария недоступны tools | тесты contracts/session |
| I9 | Выбор среди допустимых — `rank()` над allowed; LLM не переопределяет порядок | тест `llm_choice_overridden` |
| I10 | 0 реальных сетевых вызовов в тестах | autouse guard `urllib.request.urlopen` в `tests/agentic/conftest.py`; factory отказывает при `PYTEST_CURRENT_TEST` |
| I11 | Секрет не попадает в repr, trace, логи, исключения, decision | тест с фиктивным ключом |
| I12 | Статусы решения только `hold/recommend_scenario/refuse`; UI и explain работают с agentic-решением | тест explain/Screen на agentic dict |
| I13 | Слои: новые модули соблюдают `test_layers.py`; в application нет подстроки `http` | architecture tests |
| I14 | Число шагов, вызовов, replans, время ограничены конфигом | тесты budget |

## 3. JSON/API совместимость

- Legacy-режим: формат, ключи, `decision_id` неизменны.
- Agentic-режим: 20 legacy-ключей с той же семантикой + один дополнительный ключ `agentic`, добавляемый **после**
  вычисления `decision_id` (id описывает детерминированное содержимое решения):

```json
"agentic": {
  "mode": "agentic",
  "outcome": "selected | confirmed_legacy | refused | fallback | skipped",
  "fallback_reason": null,
  "legacy_decision_id": "…",
  "legacy_status": "hold",
  "provider": "zai", "model": "glm-5.3-flash",
  "llm_calls": 5, "usage": {"prompt_tokens": 0, "completion_tokens": 0},
  "constraints_applied": [ … ], "vetoed_candidates": [ … ],
  "llm_choice_overridden": false,
  "opinions": {"quality": {…}, "reliability": {…}},
  "trace": [ AgentTraceEvent … ],
  "note": "LLM не вычисляет числа и не признаёт допустимость; решение проверено Gate."
}
```

- `refusal.kind` получает новое значение `agent_rejected` только в agentic-режиме; `explain_refusal` обязан его отображать
  (fallback на общий текст отказа).
- HTTP `/v1/decisions`, `/v1/live/advice`: форма ответа прежняя; `decision.agentic` появляется только при включённом флаге.

## 4. Поведение при сбоях

| Сбой | Поведение |
|---|---|
| Флаг явно выключен (`AGENTIC_DECISION_ENABLED=0`) | Legacy, LLM-клиент не создаётся, .env не читается. По умолчанию слой включён (решение 16.09) |
| Флаг включён, ключ/настройки не заданы | Legacy + `agentic.outcome=fallback`, `fallback_reason=llm_not_configured` |
| Timeout / сеть / 5xx / 1302 / 1305 | ≤1 повтор (только retryable), затем fallback |
| 401 / 1113 / 1308–1315 (квота, план, ToS) | Без повторов, fallback |
| Malformed tool args / opinion | 1 локальный repair → 1 корректирующий вызов → opinion UNKNOWN (специалист) или fallback (оркестратор) |
| Неизвестный tool / tool не в allowlist | Структурная ошибка в ответ LLM, считается шагом |
| Исключение внутри tool | `{"error": "…"}` в ответ LLM, trace; не валит решение |
| Исчерпан бюджет вызовов/шагов/времени | Fallback (если нет finalize) |
| Выбор id вне allowed | Legacy |
| Guard не пройден | REFUSE `final_recheck_failed` |
| Любое непредвиденное исключение agentic-слоя | Legacy + fallback (`unexpected_error:<тип>`) |
