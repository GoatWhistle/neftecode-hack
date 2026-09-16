# 01. Целевая архитектура multi-agent слоя

## 1. Принцип

```
LLM рассуждает, выбирает tools, предлагает.
Детерминированный код считает, проверяет, ранжирует и имеет последнее слово.
```

LLM никогда не источник технологических чисел и не может обойти Gate. Любой сбой LLM возвращает систему в
детерминированный legacy-результат (не менее безопасный, чем сейчас).

## 2. Агенты и tools

Настоящие LLM-агенты (bounded tool-using loops):

| Агент | Цель | Может | Не может |
|---|---|---|---|
| `OrchestratorAgent` | Найти безопасный объяснимый план или честно HOLD/REFUSE | выбирать следующий tool, опрашивать специалистов, запускать поиск с ужесточающими ограничениями, завершать | ранжировать сам, выбирать недопустимый план, менять пределы |
| `QualityAgent` | Оценить запас качества продукта с учётом неопределённости и данных | запрашивать запасы, траектории, прогноз/неопределённость, проекцию резервуара, look-ahead, robustness, сравнения; предлагать ограничения | считать свойства, признавать план допустимым |
| `ReliabilityAgent` | Оценить эксплуатационную разумность формально допустимого плана | запрашивать изменения уставок, близость к границам, загрузку отбора, запасы, robustness; предлагать ограничения | проверять hard constraints вместо Gate |

Декомпозиция на три агента сохранена: data trust остаётся детерминированным правилом (LLM не должна «спасать» плохие
данные), optimizer — детерминированный tool. Отдельный LLM-агент данных не добавляется.

Детерминированные TOOLS / ENVIRONMENT (не меняются): `DataTrustAgent`, forecast (`infrastructure/ml`), response effect
port, `CandidateGenerator`/`PlanOperation.build_plans`, `PlanOperation.evaluate` (ChainModel, Blender, InventoryLedger,
Economics), `check_plan` (Gate), `rank`, `RobustnessCheck`, `planner.lookahead`, legacy `QualityAgent`/`ReliabilityAgent`
validators.

## 3. Размещение кода

```
application/ports/llm.py                 LLMClient Protocol, LLMMessage/LLMResponse/ToolCall/ToolSpec, LLMError
application/ports/response_effect.py     ResponseEffectProvider Protocol
application/agentic/
  contracts.py      Opinion, AgentConstraint (закрытый словарь), OrchestratorFinal, AgentSettings, AgentTraceEvent, parse_*
  budget.py         AgentBudget (вызовы, шаги, replans, deadline), BudgetExhausted
  context.py        компактный AgentContext (shortlist, запасы, данные) с лимитом символов
  session.py        DecisionSession: кэш Evaluation/PlanCandidate, фильтры ограничений, shortlist, robustness/lookahead кэш
  tools.py          ToolRegistry, определения tools, allowlist по агенту, обрезка результата
  loop.py           run_tool_loop: общий bounded цикл LLM ↔ tools, repair, forced submit
  quality.py        QualityAgent
  reliability.py    ReliabilityAgent
  orchestrator.py   OrchestratorAgent
  decision.py       AgenticMakeDecision: legacy → agents → deterministic resolution → release → guard → fallback
infrastructure/llm/
  config.py         env + минимальный .env-парсер, Secret, LLMSettings, AgentSettings из env
  errors.py         маппинг HTTP/Z.AI кодов в LLMError
  openai_compatible.py  Z.AI Coding Plan и OpenAI (Chat Completions + tools)
  anthropic.py      Anthropic Messages API (tools)
  scripted.py       ScriptedLLM, PolicyLLM (детерминированные, без сети)
  factory.py        make_llm_client(settings)
infrastructure/response/unavailable.py   ResponseEffectProvider: «не интегрирован»
infrastructure/agentic/factory.py        decision_factory(env): MakeDecision | AgenticMakeDecision
```

## 4. Граница legacy ↔ agentic

`MakeDecision` получает две behaviour-preserving экстракции: `_search(...)` (петля раундов, возвращает `SearchOutcome`)
и `release(...)` (look-ahead → final recheck → robustness → `_finish`). `decide()` вызывает их в прежнем порядке; golden
hash подтверждает идентичность. `AgenticMakeDecision` использует те же `_search`/`release`, поэтому финальная проверка,
look-ahead и robustness у двух путей — один и тот же код.

Флаг `AGENTIC_DECISION_ENABLED` (с 16.09 по решению пользователя включён по умолчанию; `0/false/no/off` — явное отключение) читается только во внешних слоях (`infrastructure/agentic/factory.py`,
вызывается из composition и services). Replay и benchmark остаются legacy.

## 5. Sequence

```mermaid
sequenceDiagram
    participant C as Caller (CLI/HTTP/demo)
    participant A as AgenticMakeDecision
    participant L as MakeDecision (legacy)
    participant S as DecisionSession + tools
    participant O as OrchestratorAgent (LLM)
    participant Q as QualityAgent (LLM)
    participant R as ReliabilityAgent (LLM)
    participant G as Gate / release (deterministic)

    C->>A: decide(state, budget, ...)
    A->>L: _search + release (legacy)
    L-->>A: legacy decision + SearchOutcome
    alt legacy REFUSE по данным
        A-->>C: legacy + agentic.outcome=skipped
    end
    A->>S: session(SearchOutcome) → shortlist ≤ K
    A->>O: compact context
    loop ≤ AGENT_MAX_STEPS, ≤ AGENT_MAX_LLM_CALLS
        O->>S: inspect / compare / search_candidates(constraints)
        S->>G: evaluate + check_plan (новые кандидаты)
        O->>Q: ask_quality(ids, focus)
        Q->>S: get_quality_margins / get_forecast_and_uncertainty / get_tank_projection ...
        Q-->>O: QualityOpinion (strict schema)
        O->>R: ask_reliability(ids, focus)
        R->>S: get_setpoint_changes / get_robustness ...
        R-->>O: ReliabilityOpinion
        O->>S: rank_allowed()
    end
    O-->>A: finalize(select | keep_legacy | refuse)
    A->>A: deterministic resolution (allowed = feasible ∩ constraints ∖ vetoes; rank)
    A->>G: release(chosen) → final recheck + look-ahead + robustness
    A->>G: guard: независимая переоценка свежим PlanOperation
    A-->>C: decision (20 legacy-ключей) + agentic{trace, usage, outcome}
    Note over A: любой LLMError / timeout / budget / invalid → legacy decision + agentic.outcome=fallback
```

## 6. Детерминированное разрешение (resolution)

1. `allowed` = кандидаты сессии с `gate.feasible` (и legacy review pass), удовлетворяющие всем **принятым** ограничениям
   (переданным в `search_candidates`), минус кандидаты с per-candidate verdict `REJECT` от любого специалиста.
2. `finalize.select(id)`: `id ∈ allowed` → выбор = `rank(allowed)` (семантика ранжирования неизменна); если выбор LLM
   отличается от `rank`, используется `rank`, расхождение фиксируется (`llm_choice_overridden`). `id ∉ allowed` → legacy.
3. `finalize.keep_legacy`: legacy-план должен быть в `allowed`; иначе `rank(allowed)` или REFUSE, если пусто.
4. `finalize.refuse`: разрешён, только если хотя бы одно мнение специалиста `REJECT`/`UNKNOWN` с `risk_level=high`;
   иначе legacy. Результат — `REFUSE`, `refusal.kind="agent_rejected"` (строго консервативнее).
5. Выбранный план идёт через `release(...)` с `feasible=allowed` (look-ahead может переключиться только внутри allowed).
6. Guard: для HOLD/RECOMMEND — независимый `PlanOperation(scenario).evaluate(plan)`; `gate.feasible` ложно → REFUSE
   `final_recheck_failed`.
7. Legacy REFUSE `no_feasible_plan`: агенту доступен один `search_candidates` по неисследованным планам; всё новое
   проходит Gate. Если feasible нет — REFUSE как в legacy.

## 7. Что LLM видит

Только компактный JSON: сценарий (id, горизонт), доверие к данным, прогноз (если live), пределы с источником,
текущий режим, итог legacy, счётчики поиска, shortlist ≤ `AGENT_MAX_CANDIDATES_FOR_LLM` карточек. Никаких сырых CSV,
траекторий всех кандидатов, полного decision JSON. Дополнительное — через tools с обрезкой результата.
