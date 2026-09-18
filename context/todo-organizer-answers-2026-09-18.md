# Что осталось доделать по пулу O01–O13 (состояние на 18.09.2026, вечер)

План пула: `tasks-organizer-answers-2026-09-18.md`. Решения пользователя: O08 — оставить 3 ч; O11 — не делать;
O12/O13 — черновик писем в `context/`, отправляет пользователь. Документы — по минимуму, упор на код.

## Сделано и закоммичено (ветка `main`)

- O01 `55a0b62` — ответы 18.09 записаны в `organizer-clarifications.md`, чат прочитан до 591.
- O02 `42c7bf3` — T95 = 360 °C `given` в пяти сценариях, `parameters.json`, тестах и живых документах.
- O03 `8f3e4de` — цена присадки 10 (`given`, 18.09), расхождение с 517 в примечаниях; проверка: при 100, 10 и 1
  ни одно из 13 решений не меняется (`additive-price-sensitivity-2026-09-18.md`).

## Сделано, но НЕ закоммичено (рабочее дерево; O04 + O05 + O06 вместе)

Код:
- `domain/production/economics.py` — `deep_treating_depth_mgkg`, `deep_treating_cost_per_t` (k·depth²),
  `on_demand_price_per_t`; `step_cost` считает очистку квадратично: depth = 0.42 мг/кг/°C × ΔT выше опорной.
- `domain/production/scenario.py` — `Tank.on_demand`, единицы `cost_per_ppm2_per_t`, `sulfur_per_degree`.
- `infrastructure/config/scenario.py` — разбор `on_demand` (без `inventory`/`cost_per_t`), `_price_on_demand`
  выводит цену: ДТ 1.0 + очистка 0.05 + 0.01·(8 − S)² → при S = 2 цена 1.41. `ECONOMICS_KINDS` заменены:
  `deep_treating_reference_mgkg` (8, given), `deep_treating_cost_per_ppm2_per_t` (0.01, scenario),
  `sulfur_depth_per_degree_mgkg` (0.42, derived из β) вместо `treating_cost_per_extra_degree_per_t`.
- `domain/production/state.py` — `TankState.on_demand`, `produced_t`; `draw()` не уменьшает запас.
- `domain/production/inventory.py` — `initial_state` передаёт `on_demand`; `draw_step` и `check_terminal`
  не проверяют остаток для on_demand.
- `evaluation/robustness.py` — возмущение «запас резерва −20 %» → «подача резерва −20 %» (`max_outflow`).
- `presentation/web/server.py`, `presentation/demo.py` — поле запаса для on_demand-бака отключено;
  `tank_inventory` для него — ошибка.
- Сценарии ×5: `reserve` → `on_demand: true`, имя «ДТ более глубокой очистки (по необходимости)», без
  `inventory`/`cost_per_t`; `light.available: false` с примечанием; блок `economics` новый; `assumptions` обновлены.
  Новый `config/scenarios/light_component.json` (копия baseline с включённым light).
- Тесты уже поправлены: `test_server.py`, `test_demo.py`, `test_benchmark.py`, `test_integration.py` (проходят).

Проверено вручную: baseline/winter_grade/light_component — `hold` 1.091; sour_crude — `c0025` (0.8/0.2, 50 т/ч);
ample_reserve — `c0160` (0.8/0.2, 100 т/ч); no_feasible — `refuse`. Цена резерва 1.41.

## Осталось

1. **Починить оставшиеся тесты** (~40, все из-за «резерв 600 т / cost 1.4 / три доступных бака»):
   - `tests/test_inventory.py` (7), `tests/test_replay.py` (3), `tests/test_planner.py` (2), `tests/test_lookahead.py`
     (1) — тесты рисуют из `reserve` и ждут уменьшения остатка: переключить на `main` или на бак без `on_demand`.
   - `tests/test_scenario.py` (3): `available_tanks == ["main", "reserve"]`; `reserve.inventory` derived, не measured —
     проверять `main`; round-trip: `to_dict` резерва не должен отдавать `inventory`/`cost_per_t` для on_demand
     (или парсер должен их допускать при `on_demand` — проще второе: убрать запрет в `_parse_tank`, игнорировать).
   - `tests/test_economics.py` (2): арифметика `100·(0.05 + 0.01·(0.42·10)²)`; тест наклона → «глубина ×2 → затраты ×4».
   - `tests/test_robustness.py::test_a_tank_stock_can_be_perturbed` — возмущать `main.inventory` или `reserve.max_outflow`.
   - `tests/test_response_guard.py` (1), `tests/test_explain.py` (1), `tests/test_planner.py::alternatives` — после
     смены сетки кандидатов альтернативы/план могут отличаться; проверить логику, не подгонять.
   - Золотые хэши: `tests/test_architecture_baseline.py::EXPECTED` (sha256 четырёх сценариев) и
     `tests/agentic/test_legacy_baseline.py::EXPECTED` (plan id `c0160`/`c0025`, production 150 у sour_crude,
     evaluated 32 у no_feasible, `decision_id`) — перебазировать на новые значения.
   - Агентные: `test_agent_demo`, `test_orchestrator_agent` (3), `test_wiring`, `test_session_tools` — scripted-политика
     ждёт `selected` на sour_crude, получает `refused`: смотреть `application/agentic/*` — вероятно, скриптовый
     провайдер ссылается на id кандидата (`c0025`/семейство `inventory`), которого больше нет или который теперь
     не проходит; поправить фикстуру/ожидание.
   - `tests/services/*` (3), `tests/test_snapshots.py`, `tests/test_ui.py` (3) — скорее всего уйдут после
     починки выше (падали по `KeyError: 'inventory'` до правки `server.py`); перепроверить.
2. **Текст для оператора (O04 критерий)**: в `application/services/explain.py` рядом со `cost` добавить строку
   «Разбавление оплачивается более глубокой очисткой: X усл.ед./т компонента (глубина 6 мг/кг ниже 8)»; в
   `presentation/web/ui.py` (строки ~146–148) остаток on_demand-бака показывать как «по необходимости», а не «0 т».
3. **Пересборка артефактов**: `uv run neftecode snapshot --all` → `scenes` → `screen --scenario config/scenarios/baseline.json`
   → `benchmark`. Проверить сцену 24.07 (`c0041` → новый id, рецепт), обновить `config/snapshot_moments.json:43` (`why`),
   `README.md:335`, `context/defence.md:51-63,186` (sour_crude «резерв 50 т» → «предел подачи»; «отключить reserve» →
   «глубокая очистка недоступна»).
4. **Коммиты O05/O04/O06** (можно одним, если разделять дорого): `feat: резерв глубокой очистки производится по
   необходимости, затраты квадратичны, лёгкий компонент выключен`. `ruff --select F src/` перед коммитом.
5. **O07** некондиция +5 %: `economics` сценария `offspec_rework_cost_share = 0.05` (given); в
   `make_decision.py:_look_ahead` добавить в `result` блок `offspec` (`rework_cost = 0.05·цена main·запас main`,
   `plan_extra_cost = Δcost_per_tonne·production_t`); выбор не менять; в `agentic/quality.py:15` заменить
   «в 50–100 раз» на «+5 % себестоимости на объём резервуара (организаторы 18.09)». Хэши перебазировать.
6. **O08** (только тексты): `config/parameters.json` → `response_lag_hours` добавить факт «30 мин – 2 ч, паспортного
   времени нет (18.09)» и `working_onset_hours 3.0 derived` с обоснованием (плато 3–8 ч, занижение намеренное);
   `config/response_model.json` → `horizon_response_source` дополнить; строки в `advisor.py:348-352`, `explain.py:242-251`.
7. **O10** (только тексты): `infrastructure/data/data.py:154-162` докстринг, строки `model_service.py:104` и
   `advisor.py:457` («ПАК скорректирован…» → «прогноз ЛИМС по ПАК с поправкой по 20 последним парам»),
   `context/state.md:384-385` («приведён к ЛИМС» убрать).
8. **O09**: короткий раздел в `context/defence.md` — обоснование β (ARX по T6, n_rows 49 105, отсечение будущего,
   β = −0.4227 [−0.4768; −0.389], область применимости, плато 3–8 ч согласуется с «от 30 мин»).
9. **O12/O13**: `context/questions-to-organizers-2026-09-18.md` — два письма (объём/оборачиваемость парка с числами
   8000 т → 0, 4000 т → 8, 2000 т → 49 советов из 140; присадка 10 или 100; лёгкий компонент; база квадрата и
   предел глубины очистки).
10. **Итог**: `context/state.md` раздел «Пул O01–O13», статусы в `tasks-organizer-answers-2026-09-18.md`, O11 отложена.

## Как продолжить

```sh
uv run pytest -q -p no:cacheprovider 2>&1 | grep -E "^FAILED|passed|failed"
```
Начать с пункта 1 (тесты), потом 2–4 и коммит, затем 5–10. Все прогоны с `AGENTIC_DECISION_ENABLED=0`.
