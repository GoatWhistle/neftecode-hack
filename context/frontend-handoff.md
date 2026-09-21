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
