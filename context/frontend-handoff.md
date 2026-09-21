# Передача фронту

Формат записи: задача, критерий готовности, контракт (поле, тип, пример JSON, чего это
касается на сервере), что поменять на фронте и где (файл/функция, если известны). Контракт
меняется только добавлением полей — старые поля не удаляются и не меняют смысл, пока фронт
не подтвердит переход.

## Z3 — тестовая инфраструктура фронта

Источник: `context/task-pool.md`, этап 0, причина 5 («У фронта нет автотестов; подписи и
статусы проверялись глазами»).

Задача: поднять тестовую инфраструктуру `src/frontend/` (vitest или аналог, совместимый с
Vite/React в этом проекте), чтобы `npm test` запускался и работал.

Критерий готовности: `npm test` (или эквивалентная команда, зафиксированная в
`src/frontend/package.json`) запускается и проходит хотя бы на каркасе (не обязательно
сразу покрывать всё — важно, что инфраструктура есть и зелёная).

Контракт: не меняется, задача инфраструктурная, серверных полей не касается.

Зависит от: ничего на сервере. Может выполняться независимо и в любой момент.

Статус: ⏳ ожидает фронта.

## N1 — самооценка уверенности агента

Источник: `context/task-pool.md`, этап 2, строка N1; уточнение объёма — `context/problems.md`,
«Аудит заявлений Z9», пункт Z9-5.

Задача: «уверенность» мнения агента — самооценка LLM, её никто не калибровал по исходам. На экране
(`ui/Opinions.tsx`) она показана числом `0.60` и полосой из пяти клеток и читается как вероятность.

Критерий готовности: в payload у `confidence` есть признак «самооценка, не калибрована» (сервер —
сделано); на экране нет числа или шкалы, похожих на вероятность (фронт).

Контракт (только добавление): в каждом элементе `agentic.opinions[]` рядом с `confidence` два поля.

| Поле | Тип | Значение |
|---|---|---|
| `confidence_kind` | string | всегда `"llm_self_report"` — самооценка модели |
| `confidence_calibrated` | boolean | всегда `false` — не калибрована, не вероятность |

`confidence` (number в [0, 1]) остаётся как был, смысл не меняется. Признак ставит сервер, LLM его
не присылает (`OPINION_FIELDS` не менялся). На сервере: `CONFIDENCE_LABEL` в
`src/neftecode/application/agentic/contract_opinions.py` (`Opinion.to_dict`) и
`opinion_summary` в `src/neftecode/application/agentic/orchestrator.py` — из него собираются
`agentic.opinions`, сводка в трассе (`resolution.tool_result_summary`) и ответ оркестратору на
консультацию. В логике решения `confidence` не участвует: `_resolve` смотрит только `verdict`,
`risk_level` и `valid`.

Пример (фактический, `sour_crude`, `LLM_PROVIDER=scripted`):

```json
{
  "role": "quality",
  "verdict": "REVISE",
  "risk_level": "medium",
  "confidence": 0.6,
  "confidence_kind": "llm_self_report",
  "confidence_calibrated": false,
  "valid": true,
  "reasons": [{"code": "thin_sulfur_margin",
               "text": "Запас по сере 0.8693 мг/кг меньше технологического 1.0",
               "candidate_id": "c0036"}],
  "candidate_verdicts": {"c0036": "REVISE"},
  "proposed_constraints": [{"type": "min_quality_margin", "limit": "sulfur_mgkg", "value": 0.5}],
  "preferred_candidates": []
}
```

Что поменять на фронте:
- `src/frontend/src/types/agentic.ts`, `AgentOpinion`: добавить необязательные
  `confidence_kind?: string` и `confidence_calibrated?: boolean` (старые записи без них).
- `src/frontend/src/ui/Opinions.tsx`, `Opinion`, блок «Уверенность»: убрать
  `<span className="opinion__conf-value">{num(confidence, 2)}</span>` и `ConfidenceBar`
  (по Z9-5 пять клеток сами по себе выглядят как шкала вероятности). Вместо них — подпись с
  причиной, например «самооценка модели, не калибрована» и грубый уровень словом
  (низкая / средняя / высокая), если `confidence_calibrated === false`. Заголовок `dt` лучше
  сменить на «Самооценка модели». Число можно оставить только во всплывающей подсказке с той же
  оговоркой.
- То же касается `ui/ConsultCard.tsx` (шкала из 10 шагов по `confidence`) и строки
  `уверенность ${opinion.confidence}` в `agents/contribution.ts` — там тоже число без оговорки.
- Снимки `public/f0405/*.json` и `dist/` сняты до N1 и новых полей не содержат; обработка
  отсутствующего признака — как у некалиброванного.

Статус: сервер — готово (поля в payload, тесты `tests/agentic`); фронт — ⏳ ожидает.

## O2 — явное состояние агентов

Источник: `context/task-pool.md`, этап 2, O2; `context/problems.md` #7.

Задача (фронт): при выключенных агентах этап 07 «Агенты» показывается как «пропущено», лампа не
горит «пройден», а режим агентов не выдаётся за работу LLM.

Критерий готовности: при `AGENTIC_DECISION_ENABLED=0` стадия 07 в состоянии `skipped`, лампа не
`pass`, заголовок режима — «агентный режим выключен», а не «отказ на проверке данных» и не
«Внешняя LLM».

Как было. При `AGENTIC_DECISION_ENABLED=0` ключа `decision.agentic` в payload нет вовсе (на фронте
`payload.decision.agentic === undefined`). `stageRan("agents")` возвращает `true`, `agentsLamp`
видит 8 детерминированных участников в `decision.trace` и горит `pass`.

Контракт (сервер, сделано). Новое поле верхнего уровня экрана, рядом с `decision`, а не внутри него:

- поле: `payload.agentic_state`;
- тип: `{ mode: "disabled"; outcome: "skipped"; reason: "agents_disabled"; note: string } | undefined`;
- есть только тогда, когда агентный слой не участвовал (`decision.agentic` отсутствует); когда агенты
  работали, поля нет, состояние по-прежнему в `decision.agentic` (там ничего не менялось);
- сервер: `src/neftecode/presentation/web/ui.py` (`AGENTS_SKIPPED`, `agentic_state`, `Screen.payload`) —
  одинаково для demo, stack (gateway), `advise` и `screen`.

```json
{
  "state": "decision",
  "decision": { "status": "hold", "trace": [ ... ] },
  "agentic_state": {
    "mode": "disabled",
    "outcome": "skipped",
    "reason": "agents_disabled",
    "note": "Агентный слой не участвовал (выключен, AGENTIC_DECISION_ENABLED=0): решение принял детерминированный код, LLM не вызывалась"
  }
}
```

Почему не `decision.agentic = {...}` и не `decision.agentic_state`. `decision` при выключенных агентах
обязан совпадать с детерминированным ядром побитово (`test_flag_off_demo_decision_is_byte_identical_to_legacy`)
и по составу ключей (`test_http_payload_keeps_the_decision_json_shape`). И объект в `decision.agentic`
фронт сейчас прочитал бы неверно: `run/mode.ts` (`modeOf`) показал бы «Внешняя LLM: провайдер не задан»,
`ui/AgenticMode.tsx` (`toneOf`) — «отказ на проверке данных» (outcome `skipped` проверяется раньше).
Отдельное поле ничего из старого не ломает: пока фронт его не читает, экран такой же, как до O2.

Что поменять на фронте:

1. `src/frontend/src/types/index.ts` — добавить в `ScreenPayload` необязательное
   `agentic_state?: { mode: string; outcome: string; reason: string; note: string }`.
2. `src/frontend/src/run/sequence.ts`, `stageRan`, ветка `"agents"` — первой строкой
   `if (payload.agentic_state?.outcome === "skipped") return false;`. Отсюда этап получает `skipped`
   и в `run/useRun.ts`, и в `run/progress.ts`.
3. `src/frontend/src/stages.ts`, `agentsLamp` — до разбора трассы:
   `if (payload.agentic_state) return { lamp: "unknown", title: "агенты выключены" };`
   (8 участников в `decision.trace` — детерминированное ядро, не агенты).
4. `src/frontend/src/ui/AgenticMode.tsx` — при `!agentic && agentic_state?.mode === "disabled"` вместо
   «Режим работы агентов не передавался» показать тон `off` и `agentic_state.note`
   (компоненту нужно передать `agentic_state` из `stages/AgentsStage.tsx`).
5. `src/frontend/src/run/mode.ts`, `modeOf` — при `agentic === null && payload.agentic_state` вернуть
   «Агенты выключены» вместо «Режим не передан».
6. `src/frontend/src/map/nodeFacts.ts`, `agentsCaption` — при `agentic_state` подпись
   `не привлекались · агенты выключены`.

Проверка на сервере: `AGENTIC_DECISION_ENABLED=0` → `agentic_state.outcome == "skipped"`, `decision.agentic`
нет; агенты включены (`LLM_PROVIDER=scripted`) → `agentic_state` нет, `decision.agentic` как раньше.

Статус: сервер готов; ⏳ ожидает фронта.

## N2 — управляемость и основание блоков цепочки

Источник: `context/task-pool.md`, этап 2, N2 (внешняя критика, п. 10). В live ходы АВТ отключены
(`src/neftecode/infrastructure/live/binding.py:65`, отклик качества на них не измерен), а на экране
АВТ стоит в цепочке наравне с ГО и смешением.

Критерий готовности (сервер): в payload у каждого блока цепочки есть `controllable` и
`model_basis`; объяснение не приписывает АВТ эффекта из данных. Выполнено.

Критерий готовности (фронт): на экране у каждого блока цепочки видно, двигает ли его советчик в
текущем режиме и на чём стоит его модель; АВТ в live не выглядит управляемым наравне с ГО.

Контракт: новое поле `explanation.chain` (есть и в решении, и в отказе; при `state: "error"`
объяснения нет). Старые поля не менялись. Сервер: `src/neftecode/application/services/chain_blocks.py`
(`chain_view`), подключено в `explain.py` и `refusal.py`.

```ts
interface ChainBlock {
  id: "avt" | "hydrotreating" | "blending";
  label: string;                        // "АВТ" | "Гидроочистка" | "Смешение"
  controllable: boolean;                // двигает ли советчик блок в текущем режиме
  controllable_reason: string;          // коротко: почему да / почему нет
  controls: Record<string, boolean>;    // по уставкам: какая перебирается (для смешения — recipe/throughput_tph/additive_dose)
  model_basis: "scenario" | "data_beta" | "scenario_kinetics" | "mass_balance";
  model_basis_note: string;             // коротко: на чём стоит модель блока
  beta_mgkg_per_c?: number;             // только при model_basis = "data_beta"
}
interface Chain { mode: "live" | "scenario"; blocks: ChainBlock[] }  // порядок: avt, hydrotreating, blending
// Explanation: chain?: Chain
```

Значения `model_basis`: `scenario` — АВТ, сценарная линейная модель, эффекта из данных нет;
`data_beta` — ГО в live внутри области отклика, эффект хода T6 = β по данным; `scenario_kinetics` —
ГО в сценарном режиме или в live вне области отклика; `mass_balance` — смешение, сера по
материальному балансу (T95 и цетановое — линейное сценарное правило, плотность — аддитивность
объёмов). `mode = "live"`, когда сценарий привязан к live-измерениям; если срез выбран, но доверие
к данным не позволило привязку, `mode = "scenario"` — так и есть по расчёту.

Фактический JSON, срез 05.01.2026 08:00 (`/api/decide`, baseline, `LLM_PROVIDER=scripted`):

```json
{"mode": "live", "blocks": [
  {"id": "avt", "label": "АВТ", "controllable": false,
   "controllable_reason": "В live-контуре ходы АВТ не предлагаются: время прохождения через промежуточные ёмкости и измеренный отклик товарного качества на эти ходы не подтверждены.",
   "controls": {"avt_furnace_outlet_temp_c": false, "crude_feed_rate_tph": false},
   "model_basis": "scenario",
   "model_basis_note": "сценарная линейная модель с заданными коэффициентами; отклик установки по данным не измерен, эффект из данных АВТ не приписывается"},
  {"id": "hydrotreating", "label": "Гидроочистка", "controllable": true,
   "controllable_reason": "советчик перебирает ходы уставок: ht_reactor_inlet_temp_c",
   "controls": {"ht_feed_flow_m3h": false, "ht_reactor_inlet_temp_c": true},
   "model_basis": "data_beta",
   "model_basis_note": "эффект хода T6 — β = -0.4227 мг/кг на °C по данным завода (artifacts/response_model.json); коэффициент кинетики пересчитан из β (k = −β/S₀)",
   "beta_mgkg_per_c": -0.4227},
  {"id": "blending", "label": "Смешение", "controllable": true,
   "controllable_reason": "советчик перебирает рецепт, выпуск и дозу присадки",
   "controls": {"recipe": true, "throughput_tph": true, "additive_dose": true},
   "model_basis": "mass_balance",
   "model_basis_note": "сера — материальный баланс по массовым долям; T95 и цетановое число — линейное сценарное правило, плотность — аддитивность объёмов"}]}
```

В сценарном режиме (срез `synthetic`) все три блока `controllable: true`, у АВТ `scenario`, у ГО
`scenario_kinetics`, у смешения `mass_balance`.

Текст объяснения тоже уточнён: в live утверждения `control.avt_*` теперь звучат «уставка
регулятора … не меняется — ход не рассматривался …; эффект этого хода на качество не оценивался»
со ссылкой `policy.disabled_control_moves`, а не «сохранить уставку регулятора», которое читалось
как выбор советчика.

Что поменять на фронте и где:

- `src/frontend/src/types/explanation.ts`, `interface Explanation` — добавить `chain?: Chain` и
  типы выше.
- Схема цепочки как строка «АВТ → гидроочистка → смешение» есть в
  `src/frontend/src/mock/AgentPresentationMock.tsx` (шапка `lr-header__copy`, строка 172): вывести
  три блока из `explanation.chain.blocks`, неуправляемый блок показать приглушённым с подписью
  «ходы отключены» и `controllable_reason` в подсказке, под каждым — метка основания модели
  (`scenario` → «сценарий», `data_beta` → «β по данным», `scenario_kinetics` → «кинетика
  сценария», `mass_balance` → «материальный баланс»).
- `src/frontend/src/stages/StateStage.tsx`, блок `readouts` с `operation.controls`: уставки,
  у которых `chain.blocks[*].controls[key] === false`, пометить «не двигается советчиком» — сейчас
  уставки АВТ и ГО показаны одинаково.
- Карта конвейера `src/frontend/src/map/graph.ts` — это этапы решения (state → … → decision),
  а не установки цепочки; её трогать не нужно.
- Если `chain` нет (старый payload, `state: "error"`), ничего не показывать вместо выдумывания
  управляемости.

Статус: ⏳ ожидает фронта.

## O1 — источник значений плана

Источник: `context/task-pool.md`, этап 2, строка O1; `context/agent-prompt.md`, «Ключевые факты» #8.

Задача: подпись происхождения у значений выбранного плана берётся из payload, а не пишется
жёстко `origin="derived"`.

Критерий готовности: срез 05.01 — у уставок АВТ подпись «scenario», у T6 — «measured»
(«измерение с установки»); без F9 у расхода сырья ГО — «scenario». Значения, которые реально
выведены расчётом (выпуск, стоимость тонны, худшая точка по сере, запас до предела), остаются derived.

Контракт (сервер готов, только добавление): новое поле `explanation.plan_origin` в payload
`/api/decide` (и в экранах `screen`/`scenes`). Поле есть и при решении, и при отказе.

- `plan_origin.immediate_action` — `object | null`: источники значений `decision.immediate_action`
  (`null`, если действия нет).
- `plan_origin.steps` — `array`: по одному объекту на каждый `decision.selected_plan.steps[i]`, в том же
  порядке и с тем же `time_hours` (при отказе — `[]`).
- Объект шага: `controls: Record<string, OriginKey>` (ключи те же, что в `controls` шага),
  `recipe: OriginKey | null`, `throughput_tph: OriginKey | null`, `additive_dose: OriginKey | null`,
  `time_hours: number`. Значения — ключи из `src/frontend/src/provenance.ts` (`OriginKey`):
  `scenario`, `measured`, `derived`, `given`. `null` — значения в шаге нет.
- `plan_origin.rule` — `string`: правило словами.

Правило на сервере (`src/neftecode/application/services/explain_types.py`, `plan_origin_view`):
значение плана, равное текущему значению сценария (после привязки среза), наследует его `source`;
значение, которое выбрал расчёт (отличается от текущего), — `derived`. Рецепт сравнивается целиком
с текущим рецептом сценария; доза присадки — с нулём (в сценарии её нет). На срезе с F9 расход
сырья ГО — `derived`: это F9·1000/ρ, пересчёт измерения, а не число сценария.

Пример (срез 05.01 без F9, решение hold, фактический вывод `/api/decide`):

```json
"plan_origin": {
  "immediate_action": {
    "time_hours": 0.0,
    "controls": {"crude_feed_rate_tph": "scenario", "avt_furnace_outlet_temp_c": "scenario",
                 "ht_reactor_inlet_temp_c": "measured", "ht_feed_flow_m3h": "scenario"},
    "recipe": "scenario", "throughput_tph": "scenario", "additive_dose": "scenario"
  },
  "steps": [{"time_hours": 0.0, "controls": {"...": "как выше"}, "recipe": "scenario",
             "throughput_tph": "scenario", "additive_dose": "scenario"}],
  "rule": "Значение плана, совпадающее с текущим значением сценария, наследует его источник ..."
}
```

С F9 отличие одно: `"ht_feed_flow_m3h": "derived"`.

Что поменять на фронте:
- `src/frontend/src/types/explanation.ts`: добавить `plan_origin?: PlanOrigin | null` в `Explanation`
  (`PlanOrigin { immediate_action: StepOrigin | null; steps: StepOrigin[]; rule: string }`,
  `StepOrigin` — как `OperationOrigin` плюс `time_hours`). Поле необязательное: старые сохранённые
  экраны его не содержат.
- `src/frontend/src/ui/Verdict.tsx`, `ActionBlock`: три `<OriginBadge origin="derived" />` заменить на
  `payload.explanation.plan_origin?.immediate_action?.controls[key]`, `...?.throughput_tph`,
  `...?.additive_dose`. Нет поля — показывать «не определено» (`OriginBadge` с `null`), а не derived.
- `src/frontend/src/stages/ChoiceStage.tsx`: бейджи у «Выпуск за горизонт» и «Стоимость тонны» —
  результат расчёта, оставить `derived`. В таблице «Шаги плана по времени» можно добавить бейдж у
  каждого чипа уставки из `plan_origin.steps[i].controls[key]` (сопоставлять по индексу или `time_hours`).
- `src/frontend/src/stages/ForecastStage.tsx`: «Худшая точка по сере» и «Запас до предела» — расчёт,
  оставить `derived`; «Предел» — `given`, как сейчас. Значений плана здесь нет, правка не нужна.
- Контрактный тест фронта (O3): на срезе 05.01 подпись T6 — «измерение», АВТ — «сценарий».

Серверные тесты: `tests/infrastructure/test_snapshots.py::test_o1_plan_values_on_2026_01_05_carry_their_real_source`
(05.01 с F9 и без F9), `tests/application/test_explain.py` (удержанное значение наследует источник,
выбранное расчётом — derived, отказ — пустой план).

Статус: сервер готов; ⏳ ожидает фронта.

## O3 — контрактные тесты фронта

Источник: `context/task-pool.md`, этап 2, O3 (причина 5: подписи и статусы проверялись глазами).

Зависит от: Z3 (`npm test` должен существовать — сейчас в `src/frontend/package.json` есть только
`dev`, `build`, `preview`, `typecheck`), O1-фронт, O2-фронт.

Задача: тесты фронта на реальные примеры payload с сервера, а не на руками написанные объекты.
Фикстуры снять с сервера (`LLM_PROVIDER=scripted uv run neftecode serve --port 8765`) и положить
в тестовую папку фронта:

- `/api/decide?scenario=baseline&fault=healthy&snapshot=20260105-080000` — живой срез;
- то же с `AGENTIC_DECISION_ENABLED=0` на сервере — агенты выключены;
- `/api/decide?scenario=no_feasible&fault=healthy&snapshot=synthetic` — отказ.

Что проверить (критерий готовности — все тесты зелёные):

1. Подпись = `source`. Бейдж происхождения у значений плана берётся из
   `explanation.plan_origin` (раздел O1). На фикстуре 05.01: АВТ — «сценарий», T6 — «измерение с
   установки», расход — «выведено». Жёсткого `origin="derived"` у значений плана не осталось:
   сейчас он в `ui/Verdict.tsx:61,73,84`, `stages/ChoiceStage.tsx:68,74`,
   `stages/ForecastStage.tsx:84,99`, `ui/Origin.tsx:40`. Там, где значение действительно выведено
   расчётом (выпуск, стоимость, худшая точка по сере, запас), `derived` остаётся.
2. «Пропущено» при выключенных агентах. На фикстуре без агентов (`agentic_state.outcome ==
   "skipped"`, ключа `decision.agentic` нет) `stageRan` для агентов не `true`, лампа
   (`agentsLamp`, `stages.ts`) не «пройден» (раздел O2).
3. Фронт вызывает только существующие маршруты. Сейчас он ходит в `/api/stream`
   (`run/stream.ts:79`) и `/api/options` (`run/options.ts:70`). Маршруты сервера:
   `serve` (`presentation/web/server.py`) — `/api/stream`, `/api/decide`, `/api/defaults`,
   `/api/scenarios`, `/api/options`; стек (`services/gateway_service.py`) — `/api/scenarios`,
   `/api/defaults`, `/api/decide`, `/api/options`, **без `/api/stream`** (дефект #10, закрывается
   на сервере задачей A6). Тест держит список путей, которые вызывает фронт, и падает на новом
   пути, которого нет в этом списке.
4. Уверенность агента (раздел N1): при `confidence_calibrated == false` на экране нет числа или
   полосы, похожих на вероятность.

Контракт: не меняется, тесты читают поля, описанные в разделах O1, O2, N1.

Статус: ⏳ ожидает фронта (после Z3).

## O4 — честная подпись Stop до A7

Источник: `context/task-pool.md`, этап 2, O4; `context/problems.md` #6.

Проблема: кнопка Stop (`map/StatusBar.tsx:166-176`, `aria-label="Остановить прогон"`,
`title="Стоп · то же самое делает клавиша Escape"`; в макете `mock/AgentPresentationMock.tsx:212`
— «Остановить») только обрывает поток на фронте (`run/useRun.ts`, `AbortController`). Расчёт на
сервере продолжается: worker — daemon-поток без отмены
(`src/neftecode/presentation/web/progress.py`). Подпись обещает отмену, которой нет.

Задача: до A7 подпись и подсказка честно говорят, что останавливается только отображение:
`aria-label="Остановить отображение"`, `title="Остановить отображение · расчёт на сервере
продолжится · Escape"`; в макете — «Остановить отображение». Поведение кнопки не меняется.

Критерий готовности: ни одна подпись Stop не обещает отмену расчёта.

После A7 (отмена через порт на сервере) подпись возвращается к «Остановить расчёт» — отдельная
запись в этом файле появится вместе с A7.

Контракт: не меняется.

Статус: ⏳ ожидает фронта.
