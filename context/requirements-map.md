# Требования ТЗ: актуальная трассировка

Основание: `context/task-review/spec-text.txt`, материалы в `task/` и уточнения организаторов.
Ниже указаны реальные модули и тесты текущего репозитория; исторические task-id намеренно не используются.
Машиночитаемые происхождение и параметры: `config/parameters.json` и `config/scenarios/*.json`.

## 1. Обязательные требования

| Требование ТЗ | Реализация | Проверка | Статус и границы |
|---|---|---|---|
| Состояние → доверие → прогноз → варианты → Gate → сравнение → ответ/отказ | `application/use_cases/get_live_advice.py`, `make_decision.py`, `plan_operation.py` | `tests/application/test_planner.py`, `test_trust.py`, `tests/domain/test_gate.py` | Реализовано в сценарной постановке; live не является контуром управления |
| Синхронизация по времени и отсутствие будущей утечки | `infrastructure/data/data.py`, `data/rules.py`, `infrastructure/ml/forecast.py` и rolling-исследование | `tests/infrastructure/test_trust_rules.py`, `test_forecast.py`, `tests/evaluation/test_forecast_rolling_research.py` | Реализовано; точное время выдачи ЛИМС ограничено входными данными |
| Приоритет ЛИМС → ПАК, зависание/пропуски/307 | `application/services/trust.py`, `infrastructure/data/quality.py` | `tests/application/test_trust.py`, `tests/infrastructure/test_trust_rules.py` | Реализовано; 307 трактуется как пропуск |
| Прогноз качества и риска выхода | `src/neftecode/infrastructure/ml/forecast.py`, `src/neftecode/evaluation/episodes.py`, `src/neftecode/application/services/risk_block.py` | `tests/infrastructure/test_forecast.py`, `tests/evaluation/test_forecast_rolling_research.py`, `tests/evaluation/test_benchmark.py` | Сера/T95 проверены по времени; exceed-upper 5% не достигнут (6.01%); причинность не доказана |
| Реальное разделение ролей и обмен | `src/neftecode/application/agentic/orchestrator.py`, `specialist.py`, `session.py`; детерминированные Gate-review роли — `src/neftecode/application/use_cases/decision/reviews.py` | `tests/agentic/test_orchestrator_agent.py`, `test_specialists.py`, `test_session_tools.py`, `test_safety.py` | Оркестратор и SpecialistAgent могут использовать LLM; численные проверки остаются кодом; LLM-оптимизатора нет |
| Ограниченные управляемые воздействия с единицами | `src/neftecode/domain/production/scenario.py`, `config/parameters.json`, `src/neftecode/infrastructure/response/data_model.py` | `tests/domain/test_scenario.py`, `tests/agentic/test_data_response_effect.py` | АВТ/ГО заданы именованными сценарными переменными; карта CSV-тегов и масштаб F15 не подтверждены |
| Жёсткие ограничения важнее экономики | `src/neftecode/domain/advisory/gate.py`, `entities.py` | `tests/domain/test_gate.py`, `tests/agentic/test_safety.py` | FAIL/UNKNOWN не проходят; commercial release запрещён |
| Сера ≤10 мг/кг, спецификации, рецепт =100% | `src/neftecode/domain/shared/primitives.py`, `src/neftecode/domain/advisory/gate.py`, `src/neftecode/domain/production/blending.py` | `tests/domain/test_gate.py`, `tests/domain/test_blending.py` | Сера, T95, цетан, плотность проверяются при наличии пределов; unknown блокирует |
| Диапазоны, доступность/отбор резервуаров, выпуск | `src/neftecode/domain/advisory/gate.py`, `src/neftecode/domain/production/inventory.py` | `tests/domain/test_inventory.py`, `tests/domain/test_gate.py` | Объёмы и диапазоны сценарные; terminal inventory только при `terminal_inventory_rule` |
| Несколько вариантов и сравнение | `src/neftecode/domain/advisory/optimizer.py`, `src/neftecode/application/services/comparison.py` | `tests/domain/test_optimizer.py`, `tests/application/test_planner.py` | Ограниченный сеточный перебор; глобальная оптимальность не заявляется |
| Лаги, переходные планы, упреждение | `src/neftecode/domain/production/process.py`, `src/neftecode/application/use_cases/decision/lookahead.py` | `tests/domain/test_process_ht.py`, `tests/application/test_planner.py` | Лаги сценарные; регулятор отдельно не моделируется |
| Тяжесть режима/надёжность с допущениями | `src/neftecode/domain/production/economics.py`, `src/neftecode/application/agentic/reliability.py` | `tests/domain/test_economics.py`, `tests/agentic/test_specialists.py` | Индекс температуры/расхода — proxy, не ресурс и не вероятность отказа |
| Устойчивость к ошибкам отклика/задержки | `src/neftecode/application/services/robustness.py`, `src/neftecode/application/use_cases/make_decision.py` | `tests/application/test_robustness.py`, `tests/agentic/test_safety.py` | Возмущения сценарные; same-model проверка; обязательный стресс неприменим без хода ГО |
| Объяснимый ответ и отказ | `src/neftecode/application/services/explain.py`, `refusal.py`, `risk_block.py` | `tests/application/test_explain.py`, `tests/application/test_application_use_cases.py` | JSON сохраняет входы, Gate, причины, план и ограничения |
| Воспроизводимый Python-запуск и трасса | `README.md`, `pyproject.toml`, `presentation/cli.py`, `presentation/reports/` | `tests/architecture/test_layers.py`, `test_architecture_baseline.py` | Ядро воспроизводимо; LLM требует local-провайдера или fallback |

## 2. Необязательные пункты

| Пункт | Реализация | Статус |
|---|---|---|
| Доверие/неопределённость | trust-отчёт, диапазоны прогноза, response CI | Частично: диапазоны есть; отдельного uncertainty-агента нет |
| Контроль качества входа | `trust.py`, `data/quality.py` | Реализовано для описанных источников |
| Dashboard | `src/frontend/`, `presentation/web/` | Реализовано как демонстрационный интерфейс |
| Pareto-front | Не реализован | Осознанно выбран лексикографический `rank()`; причина — выбранное правило отбора, а не отсутствие весов |
| Дополнительные агенты | Оркестратор, качество, надёжность | Ограниченный слой; генератор кандидатов и Trust остаются кодом |

## 3. Управляющие переменные и допущения

Сценарий разрешает только поля из `stages.*.controls`; для каждого есть `min`, `max`, `current`, `step`
и `actuation`. Модель последствий использует `ht_reactor_inlet_temp_c` и `ht_feed_flow_m3h` в
сценарной шкале. В live `bind_measurements` отключает предложения по расходу сырья и температуре АВТ:
подтверждённой карты уставка → CSV-тег нет. Масштаб `F15` несогласован с F9, расход берётся из сценария.

Сера смешивается массовым балансом; T95 и цетан — сценарное линейное приближение; плотность —
аддитивность объёмов. Присадка ограничена дозой, не удаляет серу; эффект по цетану сценарный.
Допущения реализованы и помечены в `domain/production/blending.py`.

## 4. Открытые границы

- `deployment_readiness.ready=false`: фактическая вместимость резервуаров и мощность глубокой очистки не получены.
- `commercial_release_allowed=false` по конструкции.
- Не доказаны экономия завода, ресурс оборудования, причинный эффект управления и независимая физическая модель.
- `evaluation/independent.py` использует то же ядро с изменёнными параметрами; опубликованный артефакт budget=400,
  runtime default=1200, поэтому его преимущество нельзя переносить на штатный запуск.
- Парето не строится; текущая политика — `rank()` с выпуском, стоимостью, тяжестью, изменениями и id.
