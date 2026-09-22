# Фикстуры

Сняты со своего неизменённого backend базы `733661f`+`16e02f0` (F1, worktree `task/audit-frontend`),
`LLM_PROVIDER=scripted uv run neftecode serve`, без внешней LLM.

Команды получения (сервер поднят на 19865, второй — на 19866 с `AGENTIC_DECISION_ENABLED=0`):

```sh
curl "http://127.0.0.1:19865/api/decide?scenario=baseline&fault=healthy&snapshot=20260105-080000" -o decide-baseline-2026-01-05.json
curl "http://127.0.0.1:19865/api/decide?scenario=no_feasible&fault=healthy&snapshot=synthetic" -o decide-no-feasible.json
curl "http://127.0.0.1:19865/api/decide?scenario=sour_crude&fault=healthy&snapshot=synthetic" -o decide-sour-crude-agents.json
curl "http://127.0.0.1:19865/api/decide?scenario=baseline&fault=both_broken&snapshot=20260105-080000" -o decide-bad-data.json
curl "http://127.0.0.1:19866/api/decide?scenario=baseline&fault=healthy&snapshot=20260105-080000" -o decide-agents-off-2026-01-05.json
```

- `decide-baseline-2026-01-05.json` — живой срез 05.01, `decision.status=hold`, есть
  `explanation.plan_origin` (АВТ=scenario, T6=measured) и `explanation.chain`. Агенты включены,
  но в этом сценарии не привлекались (нет консультаций) — используется для проверки, что
  «нет консультаций» не превращается в «нет допустимого плана».
- `decide-no-feasible.json` — отказ `no_feasible_plan`, `decision.status=refuse`, agents on.
- `decide-sour-crude-agents.json` — агенты реально консультировались, есть `agentic.opinions[]`
  с `confidence_kind="llm_self_report"`, `confidence_calibrated=false`.
- `decide-bad-data.json` — `fault=both_broken`, `explanation.kind="bad_data"`,
  `decision.agentic.outcome="skipped"`, `fallback_reason="data_refusal"` — агенты пропущены
  из-за отказа по данным, не из-за выключения.
- `decide-agents-off-2026-01-05.json` — второй сервер с `AGENTIC_DECISION_ENABLED=0`:
  `agentic_state={mode:"disabled",outcome:"skipped",reason:"agents_disabled",...}`,
  `decision.agentic` отсутствует.

Негативные/изменённые примеры (тестовые мутации, НЕ реальный вывод сервера) — файлы с
суффиксом `.mutated*.json`; каждый такой файл явно помечен в комментарии теста, который его
использует, и не выдаётся за реальный прогон backend.

- `decide-baseline-2026-01-05.mutated-old-contract.json` — тестовая мутация: тот же срез 05.01,
  вручную вырезаны `plan_origin`/`chain`/`confidence_kind`/`confidence_calibrated`, эмулирует
  старый payload до O1/N2/N1. Используется `ui/OldContract.test.tsx`.

- `stream-baseline-2026-01-05.sse` — полная запись `/api/stream?scenario=baseline&...` того же
  сервера, `curl -N`, без правки вручную: phase → stage(×N) → agent(×N) → screen → end.
  Используется `run/stream.test.ts` как основной (позитивный) прогон; там же — два производных
  негативных потока (404 без тела, обрыв до `screen`), явно помеченных в тесте как не-запись.

## F6 — маршруты (O3, пункт 3)

Фронт вызывает ровно два маршрута: `/api/stream` (`run/stream.ts`) и `/api/options`
(`run/options.ts`) — проверено `grep -rn "fetch(\`/api" src/run`, не по памяти.
Оба реально запрошены у неизменённого `serve` этой базы (не у `neftecode-stack`, у которого
`/api/stream` не реализован — известный дефект #10, серверная сторона):

```sh
curl -s --max-time 5 "http://127.0.0.1:19865/api/options?scenario=baseline"
# → 200, реальный JSON с scenarios/faults/snapshots/decision_timeout_s
curl -s --max-time 60 -N "http://127.0.0.1:19865/api/stream?scenario=baseline&fault=healthy&snapshot=20260105-080000"
# → 200, SSE: phase → stage → agent → screen(decision.status=hold) → end
```

Оба ответа — реальные, не переписанный вручную список путей. Это подтверждает, что фронт
получает options и screen по SSE у своего `serve`; про 404 `/api/stream` у стека это ничего
не говорит и не объявляет его исправленным — тот дефект чинит A6 на сервере.

- `protocol-export-2026-09-22.json` — настоящий экспорт протокола A/B из браузерной приёмки 22.09
  (A — риск `sour_crude`/healthy, B — тот же срез с `both_broken`, отказ). Хранится без изменений:
  проверяет, что прежние экспорты нашей версии схемы по-прежнему открываются.
