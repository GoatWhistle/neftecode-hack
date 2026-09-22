# Как читать код проекта

## Главное

Проект делает две связанные вещи:

1. По истории строит прогноз серы и T95.
2. По прогнозу и сценарию перебирает варианты работы установки, проверяет их и выдаёт
   `hold`, `recommend_scenario` или `refuse`.

Основное решение принимает `application/use_cases/make_decision.py`. Начинать чтение со всего
`infrastructure/ml/` не нужно: там подготовка данных, обучение и старый словарный координатор.

## Путь одного сценарного решения

```text
config/scenarios/*.json
        ↓
infrastructure/config/scenario.py       читает и проверяет JSON
        ↓
domain/production/scenario.py           превращает его в строгий Scenario
        ↓
application/use_cases/make_decision.py  запускает агентов и цикл поиска
        ↓
application/use_cases/plan_operation.py строит и рассчитывает планы
        ↓
domain/production/*                     АВТ, ГО, смешение, запасы, экономика
        ↓
domain/advisory/gate.py                 обязательные проверки
        ↓
domain/advisory/optimizer.py            выбор среди допустимых вариантов
        ↓
application/services/explain.py         понятное объяснение
        ↓
CLI / HTTP / браузер                    показывает результат
```

### Что делают агенты

- `DataTrustAgent` проверяет свежесть, пропуски и согласованность источников. Плохие данные дают отказ
  до расчёта плана.
- `Optimizer` создаёт варианты рецепта, выпуска, присадки и небольших изменений уставок.
- `QualityReview` читает проверки серы, T95, цетанового числа и плотности. Нарушение или неизвестный обязательный
  предел запрещает вариант.
- `ReliabilityReview` читает проверки запасов, отбора из резервуаров, диапазонов уставок и присадки.
- `MakeDecision` управляет порядком: варианты → проверки → запреты → изменённый поиск → финальная
  перепроверка → решение или отказ.
- `RobustnessCheck` повторяет расчёт с отклонёнными коэффициентами и помечает хрупкий план.

Проверяющие классы качества и надёжности (`QualityReview`, `ReliabilityReview` в
`application/use_cases/decision/reviews.py`) — обычные Python-классы с чёткими правилами и не вызывают LLM.
Одноимённые по роли LLM-специалисты — `QualityAgent` и `ReliabilityAgent` в `application/agentic/`.
LLM-слой оркестратора находится отдельно в `application/agentic/`; он выбирает инструменты и сужает
множество кандидатов, но не вычисляет числа и не меняет Gate.

## Путь live-решения с моделью

```text
gateway-service
  → decision-service
      → GetLiveAdvice
          → data-service: сценарий и состояние на выбранное время
          → model-service: прогноз и диапазон
          → MakeDecision: тот же цикл агентов
  → ответ браузеру
```

- `services/data_service.py` владеет исходными данными и собирает snapshot.
- `services/model_service.py` единственный загружает обученную модель.
- `application/use_cases/get_live_advice.py` задаёт единственный порядок сборки live-решения.
- `services/decision_service.py` подключает к нему HTTP-адаптеры данных и модели.
- `services/gateway_service.py` отдаёт HTML и переводит браузерные запросы в запросы сервисов.
- `services/stack.py` запускает все четыре процесса.
- `services/common.py` содержит общий HTTP-формат, ошибки, лимиты и клиент.

## Что лежит в каждой папке

### `domain/`

Чистые правила задачи без CSV, HTTP и интерфейса.

- `shared/primitives.py` — общие статусы, ошибки и типы происхождения значений.
- `shared/actions.py` — описание управляющих действий.
- `monitoring/entities.py` — наблюдения, состояние установки и прогнозы.
- `production/scenario.py` — полный контракт сценария и его единицы.
- `production/process.py` — сценарные модели АВТ и гидроочистки с задержкой.
- `production/blending.py` — расчёт смеси по сере, T95, цетану и плотности.
- `production/inventory.py` — движение запасов резервуаров по времени.
- `production/park.py` — состояния партии и статусная машина физического резервуара.
- `production/park_evaluator.py` — единый расчёт траектории парка и массового баланса.
- `production/economics.py` — условные затраты и показатели нагрузки.
- `production/state.py` — состояние резервуара и другие состояния производства.
- `advisory/entities.py` — план, результат проверки и решение.
- `advisory/gate.py` — единая точка обязательных запретов.
- `advisory/optimizer.py` — генерация кандидатов и их ранжирование.

### `application/`

Сценарии работы системы: в каком порядке вызвать правила.

- `contracts.py` — входы и выходы сценариев использования.
- `ports/` — интерфейсы для моделей, данных, сценариев и сохранения результатов; `ports/scenarios.py` —
  `ScenarioRepository` (список сценариев, сырой JSON, загрузка `Scenario`) и `SnapshotRepository`
  (срезы по времени с подписью `label`, загрузка среза по ключу).
- `conditions/changes.py` — правки сценария (`apply_change`, `apply_changes`, таблица `CHANGES`).
- `conditions/faults.py` — инъекции отказов источников (`SOURCE_FAULTS`: `frozen_pak`, `stale_lab`,
  `both_broken`, `missing_telemetry`), синтетическое исправное состояние и `state_under` — состояние
  среза с наложенным отказом.
- `conditions/canonical.py` — значения панели по умолчанию (`defaults_for`), полные условия расчёта
  (`canonical_conditions`, по ним кэшируется решение) и правки из условий (`changes_from`).
- `services/trust.py` — проверка доверия к данным.
- `services/explain.py` — перевод решения в понятный текст.
- `services/robustness.py` — устойчивость выбранного плана к ошибкам коэффициентов (`RobustnessCheck`).
- `services/tank_estimate.py` — оценка резервуара после выбранного плана (`TankEstimateCheck`).
- `services/park_phase.py` — перебор трёх фаз τ, когда live-срез не содержит фактической стадии парка.
- `use_cases/plan_operation.py` — расчёт одного или нескольких планов.
- `use_cases/make_decision.py` — основной цикл агентов.
- `use_cases/get_live_advice.py` — вход для решения на реальных временных данных.
- `use_cases/replay_decisions.py` — повтор прошлых решений с фактическими действиями.

### `infrastructure/`

Техническая работа с файлами и моделями.

- `data/data.py` — чтение телеметрии и сбор обучающей таблицы.
- `data/quality.py` — чтение рядов качества и отчёт доступности.
- `data/vak_workbooks.py` — чтение формул и листов ВАК.
- `ml/forecast.py` — обучение и сравнение прогнозных моделей.
- `ml/risk.py` — отдельная модель риска превышения.
- `live/advisor.py` — адаптер live-данных к прикладному сценарию.
- `live/origin.py` — запрет применения модели раньше даты её калибровки.
- `config/scenario.py` — разбор и проверка JSON-сценариев.
- `scenarios/file.py` — `FileScenarioRepository` (`config/scenarios/*.json`) и `FileSnapshotRepository`
  (`artifacts/snapshots/*.json` через `live/snapshots.load_snapshots`).
- `scenarios/http.py` — `HttpScenarioRepository`: сценарии от data-service (`/v1/scenarios`,
  `/v1/scenarios/get`), так их берёт gateway.
- `artifacts/json_sink.py` — сохранение результатов.

### `evaluation/`

Содержит только offline-проверки и исследовательские расчёты для batch-команд; рантайм решения
этот пакет не импортирует:

- `benchmark.py` — сравнение советчика с простым правилом.
- `episodes.py` — эпизоды превышений, мигание и упреждение.
- `lag.py` — поиск временных задержек.
- `vak.py` — проверка формул виртуальных анализаторов.

### `presentation/`, `services/`, `bootstrap.py`

- `presentation/cli.py` только разбирает аргументы командной строки.
- `presentation/demo.py` управляет демонстрационными сценами; условия применяет через `application/conditions`.
- `presentation/web/` формирует экран и старый локальный HTTP-интерфейс; `web/query.py` только разбирает
  query-строку условий в простые значения, `web/cache.py` — кэш решений по canonical-условиям.
  `DemoService` получает сценарии через `ScenarioRepository`; файлы в presentation читает только
  `web/static.py` (статика фронта).
- `services/` содержит четыре отдельных HTTP-процесса.
- `bootstrap.py` сохраняет публичную точку запуска и совместимые функции.
- `composition/decision.py` подключает парсер, ядро, robustness и экран.
- `composition/training.py` собирает обучение и сохранение моделей.
- `composition/demo.py` формирует demo и исторический replay.
- `composition/commands/` содержит dispatcher и отдельные обработчики команд.
- `presentation/reports/experiment.py` формирует текст Markdown-отчёта; метрики читает и `report.md`
  пишет `composition/demo.py`.

## Где сейчас легко запутаться

Контур агентов теперь один: `application/use_cases/make_decision.py`. Старый словарный Coordinator
и его отдельный demo-конфиг удалены; demo и исторический replay вызывают тот же `MakeDecision`.

Сборка конкретных адаптеров находится во внешнем `composition/`. Внутренние слои его не
импортируют. CLI-обработчики разнесены по назначению; `bootstrap.py` содержит 23 строки.

## Порядок чтения на один вечер

1. `config/scenarios/baseline.json` — увидеть все реальные входные числа.
2. `domain/production/scenario.py` — понять, во что превращается JSON.
3. `domain/advisory/optimizer.py` — увидеть, какие варианты создаются.
4. `application/use_cases/plan_operation.py` — проследить расчёт одного плана.
5. `domain/production/process.py` — понять модель АВТ и ГО.
6. `domain/production/blending.py`, `park.py` и `park_evaluator.py` — смесь, партии и расписание парка.
7. `domain/advisory/gate.py` — увидеть все причины запрета.
8. `application/use_cases/make_decision.py` — собрать весь цикл агентов.
9. `services/decision_service.py` — понять HTTP-вход.
10. `bootstrap.py` — только после понимания ядра.

После каждого файла смотреть одноимённый тест. Например, после `gate.py` открыть `tests/test_gate.py`,
после `make_decision.py` — `tests/test_orchestrator.py`.

## Как исследовать руками

```bash
uv run neftecode scenes --root . --out artifacts
uv run pytest tests/test_orchestrator.py -q
uv run pytest tests/test_gate.py -q
uv run pytest tests/test_process_avt.py tests/test_process_ht.py -q
```

Самый полезный эксперимент: скопировать `config/scenarios/baseline.json`, изменить серу сырья,
запас резервуара или предел качества и сравнить `decision`, `agent_trace` и причины запретов.
Исходный сценарий при этом не менять.
