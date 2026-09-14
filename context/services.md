# Сервисная архитектура

Актуально после T44 и исправления T41/T43, 2026-09-14.

Проект остаётся monorepo, но расчётные границы запускаются четырьмя независимыми Python-процессами. `neftecode-stack` запускает их через `sys.executable -m`, проверяет `healthz`/`readyz` и при ошибке завершает process groups.

| Процесс | Порт | Владеет | Зависит от |
|---|---:|---|---|
| data-service | 8766 | `config/scenarios`, `task/`, snapshots и trust | файловая система |
| model-service | 8767 | `artifacts/model.pkl`, `manifest.json`, forecast | bundle и manifest |
| decision-service | 8768 | `MakeDecision`, binding прогноза, live orchestration | data + model HTTP |
| gateway-service | 8765 | HTML и legacy `/api/*` интерфейс | data + decision HTTP |

Поток live-запроса: gateway или клиент обращается к decision `/v1/live/advice`; общий GetLiveAdvice в decision получает сценарий и snapshot из data, передаёт полный snapshot в model, связывает верхнюю границу прогноза со сценарием и запускает доменное решение. Ни один service process не импортирует другой; общим transport-слоем является только `services.common`.

## Контракты и endpoints

Data: `GET /v1/scenarios`, `POST /v1/scenarios/get` с `{scenario_id}`, `GET /v1/capabilities`, `POST /v1/snapshots` с `{at}`. Snapshot содержит `schema_version`, `at`, `state`, `trust`, JSON `features`, `trust_config`, `source_period`, `feature_schema`, `feature_schema_hash` и `snapshot_id`. `snapshot_id` — SHA-256 канонического содержимого без самого идентификатора; pandas/numpy наружу не проходят.

Model: `GET /v1/models`, `POST /v1/forecast` с `{snapshot, fallback}`. Он проверяет структуру и хеши snapshot, совпадение `at` и `state.decision_time`, диапазон источника, `trust.usable` и полный набор признаков. Ответ содержит `model`, `value`, `lower`, `upper`, `available`, `reason` и `at`.

Decision: `POST /v1/decisions`, `POST /v1/live/advice`, `GET /v1/capabilities`. Gateway сохраняет `/`, `/index.html`, `/api/scenarios`, `/api/defaults`, `/api/decide`; envelope новых endpoints имеет `contract_version=v1`.

## Запуск и настройки

Отдельно: `uv run neftecode-data`, `uv run neftecode-model`, `uv run neftecode-decision`, `uv run neftecode-gateway`. Полный запуск: `uv run neftecode-stack --root . --artifacts artifacts`.

Supervisor принимает `--host`, `--data-port`, `--model-port`, `--decision-port`, `--gateway-port`, `--root`, `--artifacts`, `--timeout`. Env: `NEFTECODE_STACK_HOST`, `NEFTECODE_DATA_PORT`, `NEFTECODE_MODEL_PORT`, `NEFTECODE_DECISION_PORT`, `NEFTECODE_GATEWAY_PORT`; CLI имеет приоритет над env, env над defaults. Отдельные процессы также принимают свой `NEFTECODE_*_HOST/PORT`.

`/healthz` показывает живой процесс. `/readyz` data означает наличие валидных сценариев; capabilities отдельно сообщает `measurements`. Model readiness означает успешную загрузку bundle и совпадающего `manifest.json`. Поэтому отсутствие `task/` не мешает сценарному decision/gateway, но ограничивает snapshots и live advice; отсутствие model artifact ограничивает model и live.

Evaluation (`benchmark`, `vak`, `episodes`) остаётся batch CLI и в supervisor не входит. Полный stack не является промышленным контуром управления и не разрешает выпуск продукции.
