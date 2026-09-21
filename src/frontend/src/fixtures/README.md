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
суффиксом `.mutated.json`, если появятся; каждый такой файл явно помечен в комментарии теста,
который его использует, и не выдаётся за реальный прогон backend.
