# Решение: структура папок в тестах (A0c)

## Выбранный вариант

**Уникальные имена модулей без `__init__.py`** — принятое ранее решение сохранено без изменений.

Второй вариант (добавить `__init__.py` во все папки `tests/`) **отклонён**.

## Обоснование

В `plan/08-progress.md:138` зафиксировано: `tests/agentic/` и `tests/services/` намеренно
живут без `__init__.py`. Пакетов нет, поэтому pytest в режиме `rootdir`-вставки складывает
все тестовые модули в одно плоское пространство имён: два файла с одинаковым базовым именем
дают ошибку импорта на стадии коллекции.

Ограничение выполнено бесплатно: все 45 перенесённых файлов **уже имели уникальные имена**,
совпадений между слоями не возникло. Переименований не потребовалось — файлы переехали
как есть (`test_scenario.py` остался `test_scenario.py` в `tests/domain/`).

Проверка: `pytest --collect-only tests` собирает 1292 теста без ошибок импорта;
`find tests -name "test_*.py" | xargs -n1 basename | sort | uniq -d` пуст.

Добавление `__init__.py` сняло бы требование уникальности, но отменило бы принятое решение
ради задачи, которая и без него решается. Цена отказа — договорённость держать имена
уникальными при добавлении новых тестов.

## Итоговая структура

```
tests/
  conftest.py          общий для всех слоёв (AGENTIC_DECISION_ENABLED=0)
  domain/          10  gate, optimizer, blending, inventory, economics,
                       process_avt, process_ht, scenario, response_guard, offspec
  application/      8  application_use_cases, planner, replay, lookahead,
                       explain, contracts, trust, orchestrator
  infrastructure/  13  data, forecast, risk, snapshots, source_rules, trust_rules,
                       avt_tags, measurement_binding, response_estimate, live,
                       time_alignment, tank_level, infrastructure_adapters
  evaluation/       7  vak, benchmark, episodes, robustness, selection,
                       forecast_rolling_research, expert_grid
  presentation/     4  ui, server, presentation_cli, demo
  integration/      4  integration, runtime, edge_cases, agents
  agentic/         18  без изменений (свой conftest, запрет сети)
  services/         6  без изменений
  architecture/     2  test_layers + перенесённый test_architecture_baseline
```

## Пути в тестах после переноса

Относительные пути вида `Path("config/scenarios/baseline.json")` резолвятся от CWD,
а pytest запускается из корня репозитория — перенос на них не влияет.

Единственная правка: `tests/evaluation/test_forecast_rolling_research.py` использовал
`Path(__file__).parents[1]`, что после углубления на уровень указывало бы в `tests/`.
Заменено на `Path(__file__).resolve().parents[2]` — та же форма, что в
`tests/agentic/_agentic_support.py` и `tests/architecture/test_layers.py`.

## Прогоны по папкам

| папка | до | после |
|---|---|---|
| domain | 306 passed | 306 passed |
| application | 207 passed | 207 passed |
| infrastructure | 161 passed, 1 skipped | 161 passed, 1 skipped |
| evaluation | 143 passed | 143 passed |
| presentation | 101 passed | 101 passed |
| integration + architecture | 51 passed (одной пачкой) | 45 + 14 = 59 passed |

Последняя строка: до переноса `test_architecture_baseline.py` считался вместе с
integration-пачкой (51 = 45 integration + 6 baseline); после он лежит в `architecture/`
рядом с `test_layers.py`, и папка даёт 14 = 8 `test_layers` + 6 baseline. Ни один тест
не потерян: 45 + 6 = 51, как и до переноса, а `test_layers` (8) в обеих колонках не менялся.

Полный `pytest --collect-only tests` собирает 1292 теста без ошибок импорта.
Полный прогон не запускался намеренно (слабая машина) — проверка велась по папкам.
