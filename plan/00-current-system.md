# 00. Текущая система (как есть на 2026-09-16, HEAD 1c795ca)

Документ описывает реально существующий код. Источник — чтение `src/neftecode/**`, `tests/**`, `config/**`,
`context/architecture.md`. Номера строк — на момент HEAD 1c795ca.

## 1. Слои и размещение

```
src/neftecode/
  domain/        advisory (entities, gate, optimizer), production (process, blending, inventory, economics, scenario),
                 monitoring, shared (primitives)
  application/   use_cases (make_decision, plan_operation, get_live_advice, replay_decisions), services (trust, explain),
                 ports (artifacts, live, measurements, models, robustness, scenario), contracts.py
  infrastructure/ config, data, ml (forecast, risk), live (advisor), artifacts
  evaluation/    robustness, benchmark, episodes, vak, lag
  presentation/  cli, demo, web (server, ui), reports
  services/      data/model/decision/gateway HTTP-процессы, stack, common
  composition/   composition root (decision, demo, training, commands/*)
```

Правила слоёв зафиксированы тестами `tests/architecture/test_layers.py` и `tests/test_architecture_baseline.py`:

- `domain` → только domain; `application` → application, domain; `infrastructure` → infrastructure, application, domain;
  `evaluation` → evaluation, application, domain; `presentation` → presentation, application, domain;
  `services` → всё, кроме composition; `composition` → всё. Новый top-level пакет в `neftecode/` запрещён.
- В тексте файлов `src/neftecode/application/**` запрещены подстроки `pandas numpy catboost sklearn openpyxl http pathlib`
  (включая комментарии и строки).
- Класс с именем `Coordinator` запрещён; flat-модули `agents.py`, `orchestrator.py` и др. в корне пакета запрещены.
- Сервисы не импортируют друг друга (только `services.common`).
- Composition импортируется только внешними точками входа.

Стек: Python 3.12, pandas, numpy, scikit-learn, CatBoost, openpyxl, pytest. HTTP — только stdlib (`http.server`,
`urllib.request`). pydantic, httpx, requests, dotenv, SDK LLM **отсутствуют**. Развёртывание — offline, закрытая сеть
(config/parameters.json `deployment_requirements`, Q&A 11.09).

## 2. Что называется «агентами» сейчас

Ни одного LLM-агента нет. «Агенты» — детерминированные Python-роли внутри `MakeDecision`.

| Имя | Где | Реальная ответственность |
|---|---|---|
| `DataTrustAgent` | application/services/trust.py:153 | Правила доверия ЛИМС/ПАК/телеметрии → `TrustReport` (usable, primary, fallback, reasons, missing) |
| `QualityAgent` | application/use_cases/make_decision.py:54 | Фильтр `gate.checks` семейства `quality.*`: считает fail/unknown, verdict pass/fail/unknown |
| `ReliabilityAgent` | make_decision.py:69 | Фильтр `gate.checks` семейств `outflow/control/inventory/additive` + `severity_index` |
| «optimizer» | domain/advisory/optimizer.py (`CandidateGenerator`, `rank`) + `PlanOperation.build_plans` | Перебор кандидатов, ранжирование |
| «orchestrator» | `MakeDecision.decide` | Порядок, veto → запреты, раунды, финальная перепроверка |

Вывод: `QualityAgent` и `ReliabilityAgent` — **validators/veto processors**, производные от Gate. Если `gate.feasible`,
все проверки PASS, и их verdict всегда `pass`. Их veto на практике меняет что-то только при внедрении другого объекта с
методом `review(evaluation) -> dict` (так делают тесты `tests/test_orchestrator.py:145-186`).

## 3. Полный текущий decision flow (`MakeDecision.decide`, make_decision.py:100-266)

1. **Явный отказ по данным**: `data_rejection` → trace `data` → `REFUSE`, `refusal.kind="data"` (106-111).
2. **DataTrust**: если `state` передан — `DataTrustAgent(trust_cfg).assess(state)`; не usable → `REFUSE data` (114-121).
3. **Ограниченная петля поиска** (`MAX_ROUNDS=3`, общий `budget`, default 600, CLI/тесты 400):
   - `PlanOperation.build_plans(budget, current_operation)` — `CandidateGenerator.generate()` (слои recipe×throughput,
     control moves по одному контролу, additive) + переходные двухшаговые планы;
   - раунд 1: `_sample_plans(plans, budget//2)` — hold + равномерный отбор постоянных и ¼ переходных;
     раунды 2+: `_feedback_candidates` — кандидаты, изменённые по семействам veto;
   - для каждого плана: `_forbidden` (запреты раунда), дедупликация по содержимому, `PlanOperation.evaluate`
     (ChainModel → InventoryLedger → Blender → Economics → `check_plan` Gate) → `Evaluation`;
   - `_review` = `QualityAgent.review` + `ReliabilityAgent.review` (через `_safe_review`: исключение или неполный ответ →
     verdict unknown);
   - `feasible` = gate.feasible И оба review pass;
   - `rank(feasible or evaluations, hold_id="hold", min_useful_gain)`; есть feasible → стоп;
   - иначе `_collect_vetoes` → `_restrict` (добавить `family:*` в forbidden) → следующий раунд; если запреты не сузили — стоп.
4. Нет выбранного → `REFUSE`, `refusal.kind="no_feasible_plan"` (205-212).
5. **Look-ahead** (`policy.lookahead_hours`, `min_reaction_hours`): `planner.lookahead` выбранного плана на 48 ч;
   если нарушение раньше запаса реакции — перебор ≤40 feasible по `key()`, возможное переключение и предупреждение (216-223, 419-472).
6. **Final recheck**: заново `planner.evaluate` выбранного плана + `_review`; trace `quality`/`reliability` stage final;
   не feasible → `REFUSE`, `refusal.kind="final_recheck_failed"` (225-241).
7. **Robustness**: если есть `raw_scenario` и evaluator — `RobustnessCheck.evaluate` (8 возмущений); fragile не блокирует,
   а добавляет предупреждение в reason (243-262).
8. Статус: `HOLD`, если `chosen.changes == 0`, иначе `RECOMMEND_SCENARIO` (253).
9. `_finish` (474-498): dict из 20 ключей, `decision_id = sha256(json(result, sort_keys))[:16]`.

Ключи результата: `status, reason, scope, current_operation, commercial_release_allowed, scenario_id, selected_plan,
immediate_action, gate, production_t, cost_per_tonne, severity_index, alternatives, rejected, refusal, robustness,
lookahead, trace, note, decision_id`.

Trace (`trace[]`): `data{usable,primary,reasons}` → `optimizer{rounds[…],max_rounds,evaluated,evaluation_budget,note}` →
`lookahead{…}` → `quality{stage:final,…}` → `reliability{stage:final,…}` → `robustness{held,evaluated,fragile}`.

## 4. Gate (domain/advisory/gate.py)

`check_plan(plan_id, trajectory, scenario, terminal)` проверяет в каждой точке: `plan.time_grid`, `quality.{sulfur,t95,
cetane,density}`, `control.*` (+ `control.X.known`), `recipe.sum/non_negative`, `additive.dose`, `throughput`,
`inventory.*`, `outflow.*`, `model.applicability`, затем `plan.discretisation` и `inventory.terminal`.
`GateResult.feasible = all(status == pass)`; `unknown` блокирует. Это единственное место признания допустимости.

## 5. rank (domain/advisory/optimizer.py:230)

Только feasible; порядок `-production_t, cost_per_tonne, severity_index, changes, candidate_id`; hold сохраняется,
если выигрыш по стоимости меньше `min_useful_gain` при том же выпуске. Возвращает `selected`, `alternatives[≤5]`,
`rejected[≤20]`, `reason`, `claim`.

## 6. Robustness (evaluation/robustness.py)

`RobustnessCheck.run(plan, …)` — 8 именованных возмущений сырого сценария, пересчёт `PlanOperation.evaluate`,
`fragile = share_holding < 1.0`. Порт — `application/ports/robustness.py`.

## 7. Live-путь

`GetLiveAdvice.execute` (application/use_cases/get_live_advice.py): snapshot → trust → (usable) forecast
(`last_pak`/`last_lab`, fallback `catboost_no_pak` при недоверии ПАК) → `bind_forecast` (приток = upper, уровень резервуара
по 42 ч, удержание при зависшем ПАК) → `_decision` (строка 79: `MakeDecision(...).decide(...)`). Недоверенные данные →
`DataRejection` → REFUSE. HTTP: `services/decision_service.py` `/v1/decisions`, `/v1/live/advice`.

## 8. Где создаётся MakeDecision

1. composition/decision.py:22 (`run_demo_decision`, демо, serve)
2. composition/commands/screens.py:25 (`screen`)
3. application/use_cases/get_live_advice.py:79 (`advise`, `/v1/live/advice`)
4. services/decision_service.py:98 (`/v1/decisions`)
5. application/use_cases/replay_decisions.py:171 (replay)
6. evaluation/benchmark.py:122 (benchmark)

## 9. Регрессионная сеть

837 тестов, ~47 с (2026-09-16). Golden: `tests/test_architecture_baseline.py::test_four_scenario_outputs_are_frozen` —
sha256 полного dict для baseline/sour_crude/ample_reserve/no_feasible (budget 400, без state). Фактические результаты:

| Сценарий | Статус | План | Evaluated | Feasible в раунде 1 |
|---|---|---|---|---|
| baseline | hold | hold | 200 | 93 |
| sour_crude | recommend_scenario | c0025 (fragile) | 200 | 2 |
| ample_reserve | recommend_scenario | c0029 | 200 | 42 |
| no_feasible | refuse no_feasible_plan | — | 200 | 0 |

Пробел: нет теста, форсирующего `final_recheck_failed`.

## 10. Response layer

`F + β_τ·ΔT` (RESPONSE_MODEL_FINAL.md v3) в src **не встроен**; эталон — `context/response-research/final/response_model.py`
(pandas/sklearn ⇒ только infrastructure). Заморожен до подтверждения семантики T11/F26 организаторами.
