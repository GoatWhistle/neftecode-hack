# Прогресс задач пула (`context/task-pool.md`)

Ведётся по мере выполнения. `task-pool.md` не переписывается — статус только здесь.

Сводка: выполнено 21 (этап 0: Z0,Z1,Z2,Z4,Z5,Z6,Z7,Z8,Z9,Z9-3,S6; этап 1: I1,I2,I3,I4,S1;
этап 2 сервер: O1,O2,N1,N2), передано фронту 7 (Z3, O1-фронт, O2-фронт, N1-фронт, N2-фронт, O3, O4),
заблокировано 0. Этапы 0–2 закрыты по серверу, всё фронтовое описано в `frontend-handoff.md`. Текущий этап: 3 (A1–A4 закрыты). С A2 после слияния гоняется быстрый набор, полный `pytest` — в конце этапа (решение владельца 21.09).

Гейт этапа 2 (21.09): полный `LLM_PROVIDER=scripted uv run pytest -q` — 1388 passed;
`npm run build` — ок; `/api/decide` по 7 случаям (`serve`, scripted): 05.01 норма — hold,
`last_pak_bc` 7.582; 05.01 + `frozen_pak` — hold, `catboost_no_pak` 7.511; 24.07 —
`recommend_scenario` c0042, `last_pak_bc` 14.933; 24.07 + `frozen_pak` — hold,
`catboost_no_pak` 8.112; `both_broken` — refuse, агенты `skipped`; `no_feasible` (synthetic) —
refuse; агенты выключены — hold, `agentic_state.outcome = skipped`. Во всех live-случаях
`plan_origin`: АВТ `scenario`, T6 `measured`, расход `derived`; `chain`: АВТ неуправляем
(`scenario`), ГО `data_beta`, смешение `mass_balance`; мнения с `confidence_kind`.
Гейт нашёл, что срезы `artifacts/snapshots` не были пересобраны после I1 (24.07 + `frozen_pak`
давал c0042): пересобраны `neftecode snapshot --all`, изменились только `forecast_no_pak` и
текст `forecast.reason`.

## Этап 0. Порядок и страховочная сетка

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| Z1 | Слить локальные `PIPELINE_PLAN.md`/`README.md` из `stash@{0}` | ✅ выполнено | `0f03f58` | `git checkout stash@{0} -- README.md PIPELINE_PLAN.md`; дерево чистое, `stash@{0}` сохранён | 2026-09-21 |
| Z2 | Полный `pytest` и `npm run build`, зафиксировать базу | ✅ выполнено | `fb22a29` | `uv run pytest -q` — 1359 passed, 0 упавших, 290 с; `cd src/frontend && npm run build` — `tsc --noEmit` чист, vite build ок (481 kB / 142 kB gzip) | 2026-09-21 |
| Z3 | Тестовая инфраструктура фронта (vitest) | 📤 передано фронту | `c602374` | `context/frontend-handoff.md` | 2026-09-21 |
| Z4 | Тест эквивалентности demo = live = gateway | ✅ выполнено (тест красный) | `334c264` | `tests/architecture/test_path_equivalence.py`: срез 2026-07-24T03:00+`frozen_pak` через demo/gateway/live (реальные HTTP-серверы); demo и gateway сходятся на устаревшем `last_pak_bc`, live пересчитывает и получает `catboost_no_pak` — падает по нужной причине (`assert 'last_pak_bc' == 'catboost_no_pak'`). Исправление — задача I1 | 2026-09-21 |
| Z5 | Регрессия 24.07 + `frozen_pak` → hold | ✅ выполнено (тест красный) | `a137c10` | `tests/infrastructure/test_snapshots.py`, 2 новых теста: `bind_snapshot` после `frozen_pak` не переключается на `catboost_no_pak`, end-to-end через `Demo`/`run_demo_decision` не даёт hold. Оба падают по нужной причине (`last_pak_bc` вместо `catboost_no_pak`). Полный `pytest -q`: 2 failed (только эти), 1357 passed, 2 skipped. Исправление — I1 | 2026-09-21 |
| Z6 | Обновить `problems.md` | ✅ выполнено | `245adf5` | #4,#5 закрыты, #7 частично, добавлены #10 (стек) и #11 (T02), правило реестра | 2026-09-21 |
| Z7 | `organizer-clarifications.md` и `parameters.json`: резервуар 5000 м³ | ✅ выполнено | `861c646` | Given-факты (5000 м³, паспорт 12 ч, слив 24 ч, дата 21.09.2026) в `organizer-clarifications.md` и `config/parameters.json` (`tank_capacity_m3`, `tank_passport_duration_hours`, `tank_drain_duration_hours`); JSON валиден; `uv run pytest -q` — 1357 passed, 2 skipped (skip старые, не от Z7 — нужны локальные `task/`+`model.pkl`) | 2026-09-21 |
| Z8 | Убрать опровергнутое заявление о преимуществе | ✅ выполнено | (не требуется — уже честно после Z1) | Проверено: README.md (пост-Z1), `context/defence.md`, `context/solution.md` — заявление о преимуществе при budget=400 уже переформулировано честно (budget 1200 → 7/7 нарушений у обеих стратегий); дополнительная правка не нужна | 2026-09-21 |
| Z0 | Файл прогресса задач (этот файл) | ✅ выполнено | `800cacd` | Файл создан, все задачи пула перенесены, ссылка в `context/README.md` | 2026-09-21 |
| Z9 | Сплошная сверка заявлений экрана/документов с кодом (владелец добавил 21.09 по внешней критике) | ✅ выполнено | `920e83c` | Таблица «заявление → основание → вердикт» в `problems.md`, раздел «Аудит заявлений Z9». Найдены 5 расхождений (не заведены как задачи пула — решение за владельцем): **Z9-1** захардкоженный «технологический запас 1 мг/кг» в `ForecastStage.tsx:98` вместо чтения из payload; **Z9-2** README называет benchmark «свежим 21.09», артефакт датирован 19.09/20.09; **Z9-3** — существенно: β T6 в прозе (README/defence/RESPONSE_MODEL_T6.md/forecast-evidence.md) = −0.4227, n_rows 49105, а в `config/response_model.json`/`parameters.json` = −0.4226, n_rows 49069 — документы прямо пишут «продукт использует −0.4227», хотя фактически в конфиге −0.4226; **Z9-4** цена присадки (10× vs 100×) в `solution.md` не привязана к конкретному полю `parameters.json` — пробел трассируемости; **Z9-5** `Opinions.tsx` ConfidenceBar — визуальная полоса уверенности, тоже похожа на вероятность, шире чем просто число из N1. Остальное (причинность, оптимальность, `commercial_release_allowed`, роль агентов) проверено — переоценок не найдено | 2026-09-21 |
| S6 | QA 21.09: уточнить у организаторов канал передачи данных и кто прикладывает трёхнедельный срез (владелец добавил 21.09) | ✅ выполнено (решение владельца без запроса) | `65e9222` | Организаторам не отправлялось: владелец выбрал безопасный вариант по умолчанию — трёхнедельный срез прикладываем сами, данные только в архив сдачи, не в публичный git. Записано в `organizer-clarifications.md`, раздел 12 | 2026-09-21 |
| Z9-3 | Расхождение β в документах и конфиге (из аудита Z9, владелец взял в работу 21.09) | ✅ выполнено | `3255ae7` | Вердикт Z9 был перевёрнут: продукт берёт β из `artifacts/response_model.json`, `estimates[τ = 2026-01-01]` (обучение 19.09) = −0.4227 [−0.4768; −0.389], n_rows 49105 — проза `RESPONSE_MODEL_T6.md`/`forecast-evidence.md` верна. Устаревшим было −0.4226 / 49069 (пересчёт 18.09): `config/parameters.json` `ht_response_beta` выровнен по артефакту (кодом не читается), `history.note` в `config/response_model.json` не трогался. Дата в `RESPONSE_MODEL_T6.md` → 19.09. Модель не менялась. `pytest tests/infrastructure tests/architecture tests/application` — 408 passed | 2026-09-21 |

## Этап 1. Корректные входы

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| I1 | Срез хранит основной и no-PAK прогноз | ✅ выполнено | `350a55b` | `build_snapshot` считает `forecast` и `forecast_no_pak`; `bind_snapshot`/`select_forecast_dict` выбирают по пересчитанному `trust.fallback_mode` — общая точка для demo/gateway/decision-service. Z4 и Z5 позеленели без изменения логики проверок (только фикстуры получили `forecast_no_pak`). Полный `uv run pytest -q`: 1360 passed, 2 skipped (было 1357+3 failed) | 2026-09-21 |
| I2 | Ход T6 только при измеренных T6 и F9 | ✅ выполнено | `17d352b` | `binding.py`: `f9 is None` больше не пропускает `in_region`; при измеренном T6 без F9 диапазон схлопывается в `min==max==current`, причина в `measurement_binding.notes`. Новый тест `test_measurement_binding.py`. `uv run pytest -q`: 1361 passed, 2 skipped | 2026-09-21 |
| I3 | Отрицательные тесты области применимости | ✅ выполнено | `92a9156` | 7 новых тестов в `test_measurement_binding.py`: T6 выше верхней границы, F9 вне своей области при T6 в области, обе границы включены, расход без F9, NaN трактуется как «не измерено». Багов не найдено, `binding.py` не менялся. Отдельная концепция «источник не в доверии» (в отличие от «не измерен») в `bind_measurements` отсутствует — задокументировано, не придумано. `uv run pytest -q`: 1368 passed, 2 skipped | 2026-09-21 |
| I4 | Разобрать прогон агентов 0,6 с | ✅ выполнено (объяснено и исправлено) | `5b77c27` | Не баг: оркестратор вправе вызвать `finalize(keep_legacy)` на первом шаге без консультации специалистов — трасса тогда честно состоит из `llm_call`+`final` (2 события), а не 20+ при полном диалоге. Не кэш, не гонка потоков. Добавлен диагностический маркер `keep_legacy_grounded`/`keep_legacy_ungrounded` в трассу, чтобы короткий прогон не выглядел аномалией при аудите. 2 новых теста в `tests/agentic/test_orchestrator_agent.py`, `tests/agentic/` — 286 passed | 2026-09-21 |
| S1 | QA 21.09: реестр исключённых периодов из данных (владелец добавил 21.09) | ✅ выполнено | `609ef8b` | `scripts/excluded_periods.py` переиспользует существующую логику детекции (`mask_stubs`, `derive_source_rules`, `conflict_mask`); реестр `context/excluded-periods.{md,json}`, ссылка в README. Прогон на полном `task/`: 1 колонка-заглушка (`avt.D10`, весь период), 4 вспышки массового 307, 112 интервалов зависания ПАК (≈2372 ч), 69 конфликтов ПАК/ЛИМС. Честно указано ограничение: класса «плановые остановки установки» как отдельного флага в данных нет. `uv run pytest -q`: 1370 passed, 2 skipped | 2026-09-21 |

## Этап 2. Честный показ

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| O1 | Backend отдаёт `source` каждого значения плана (сервер) | ✅ выполнено | `ac4dc32` (общий с N2) | Новое поле `explanation.plan_origin` (`decision` заморожен): у каждой уставки, рецепта, выпуска, дозы — источник; значение равно текущему после привязки среза → его источник, изменено планом → `derived`. Срез 05.01: АВТ `scenario`, T6 `measured`, расход с F9 `derived` (F9·1000/ρ), без F9 `scenario`. 5 новых тестов; полный `pytest` N2+O1 на main — 1388 passed | 2026-09-21 |
| O1-фронт | Подпись = `source` | 📤 передано фронту | | `frontend-handoff.md`, раздел «O1 — источник значений плана» | 2026-09-21 |
| O2 | `agentic == null` → «пропущено» (сервер) | ✅ выполнено | `b98117c` | При отключённых агентах ключа `decision.agentic` нет (не `null`); `decision` заморожен побитово, поэтому явное состояние — новое поле экрана `agentic_state = {mode: disabled, outcome: skipped, reason, note}` (`presentation/web/ui.py`, `Screen.payload`), при включённых агентах поля нет. Реальный `decide` baseline: `=0` → `skipped`, `scripted` → `decision.agentic` без изменений. 5 новых тестов; полный `LLM_PROVIDER=scripted uv run pytest -q` (N1+O2 на main) — 1377 passed | 2026-09-21 |
| N1 | Сервер: признак некалиброванной самооценки у `confidence` (владелец добавил 21.09) | ✅ выполнено | `a804e3f` | `CONFIDENCE_LABEL` (`confidence_kind: llm_self_report`, `confidence_calibrated: false`) в `Opinion.to_dict` и `opinion_summary` — доходит до `agentic.opinions[]` экрана, трассы и ответа оркестратору; от LLM поле не требуется (`OPINION_FIELDS` без изменений); `confidence` в логике решения не используется. 2 новых теста; `uv run pytest -q tests/agentic tests/presentation` — 389 passed; в worktree полный — 1372 passed, 2 skipped | 2026-09-21 |
| N1-фронт | Убрать число «уверенности» | 📤 передано фронту | | `frontend-handoff.md`, раздел «N1 — самооценка уверенности агента» | 2026-09-21 |
| N2 | Сервер: `controllable` и `model_basis` у блоков цепочки (владелец добавил 21.09) | ✅ выполнено | `ac4dc32` (общий с O1) | Новое поле `explanation.chain` = `{mode, blocks}` (`chain_blocks.py`), и в решении, и в отказе. Срез 05.01 live: АВТ `controllable=false`, `scenario`; ГО `data_beta` (β по τ среза, −0.4227), управляем только T6; смешение `mass_balance`. Текст объяснения для отключённых ходов АВТ: «ход не рассматривался; эффект на качество не оценивался». 6 новых тестов; полный `pytest` — 1388 passed | 2026-09-21 |
| N2-фронт | Управляемость блоков на схеме | 📤 передано фронту | | `frontend-handoff.md`, раздел «N2 — управляемость и основание блоков цепочки» | 2026-09-21 |
| O2-фронт | Этап «пропущено» | 📤 передано фронту | | `frontend-handoff.md`, раздел «O2 — явное состояние агентов» | 2026-09-21 |
| O3 | Контрактные тесты фронта | 📤 передано фронту | | `frontend-handoff.md`, раздел «O3 — контрактные тесты фронта»: фикстуры с сервера, подпись = `source`, «пропущено» при выключенных агентах, только существующие маршруты | 2026-09-21 |
| O4 | Подпись «Остановить отображение» до A7 | 📤 передано фронту | | `frontend-handoff.md`, раздел «O4 — честная подпись Stop до A7»: `map/StatusBar.tsx`, макет | 2026-09-21 |

## Этап 3. Архитектура

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| A1 | `QualityReview` / `ReliabilityReview` | ✅ выполнено | `0a3c213` | `decision/agents.py` → `decision/reviews.py`, классы `QualityAgent`/`ReliabilityAgent` → `QualityReview`/`ReliabilityReview`; строковые имена трассы (`quality`, `reliability`), инструменты и JSON не менялись. Новый тест `test_deterministic_reviews_do_not_share_names_with_llm_agents`. Эталоны не перефиксированы; полный `pytest` на main — 1389 passed | 2026-09-21 |
| A2 | `robustness`, `tank_estimate` → `application/services` | ✅ выполнено | `936db7c` | `git mv` обоих модулей и их тестов в `application/services` / `tests/application`, потребители обновлены (только импорты), без shim. `ALLOWED["services"]` без `evaluation`; новый `test_runtime_does_not_import_offline_evaluation` (application, composition, infrastructure, presentation, services). Исключение: `composition/commands/evaluation.py` — CLI offline-исследований (benchmark, episodes, vak, expert_grid), явно в `OFFLINE_ENTRY_POINTS`. Эталоны бит-в-бит; у агента полный `pytest` — 1388 passed, 2 skipped (gitignored данные); на main быстрый набор (architecture, integration, services, затронутые) — 167 passed | 2026-09-21 |
| A3 | Условия и инъекции → `application/conditions` | ✅ выполнено | `10e47d0` | `presentation/web/conditions.py` → `application/conditions/canonical.py` (`git mv`) + `changes.py` (правки сценария) + `faults.py` (инъекции, общий `state_under` вместо двух копий в `Demo.run` и gateway); в presentation только разбор query (`web/query.py`) и кэш (`web/cache.py`). Правило `test_conditions_logic_lives_only_in_application`. Эталоны и `test_path_equivalence` бит-в-бит. Отличие: при двух ошибках сразу (неизвестный `fault` + нечисловое поле) сообщается ошибка числа. У агента полный `pytest` — 1389 passed, 2 skipped; на main быстрый набор — 215 passed | 2026-09-21 |
| A4 | Порты `ScenarioRepository` / `SnapshotRepository` | ✅ выполнено | `<см. след. коммит>` | Порты в `application/ports/scenarios.py`; `infrastructure/scenarios/file.py` (сценарии и срезы) и `http.py` (сценарии через data-service, как gateway и делал). HTTP-репозитория срезов нет: сохранённые срезы по HTTP нигде не отдаются, gateway читает их локально — так и оставлено. `Demo.from_path` удалён, `DemoService`/`GatewayService`/`DataService` получают репозитории из composition. Попутно `reports/experiment.py` без файлового I/O (`make_report` возвращает текст, запись в composition; текст сверен агентом на копии метрик). Правило `test_presentation_reads_scenarios_and_snapshots_only_through_repositories` (исключение — `web/static.py`). Эталоны бит-в-бит; у агента полный `pytest` — 1393 passed, 2 skipped; на main быстрый набор — 367 passed | 2026-09-21 |
| A5 | Единый `AdviseUnderConditions` | ⏳ ожидает | | | |
| S2 | QA 21.09: `neftecode replay --from … --to …` через `AdviseUnderConditions` (сразу после A5, владелец добавил 21.09) | ⏳ ожидает | | | |
| A6 | Один веб-адаптер, `/api/stream` в стеке | ⏳ ожидает | | | |
| A7 | Прогресс и отмена через порт | ⏳ ожидает | | | |
| A8 | Ужесточить `test_layers` | ⏳ ожидает | | | |

## Этап 4. Модель резервуара

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| T1 | Записать решения 21.09 в `parameters.json` | ⏳ ожидает | | | |
| T2 | Домен: резервуары со стадиями | ⏳ ожидает | | | |
| T3 | Сценарии и `parameters.json`: 5000 м³, стадии | ⏳ ожидает | | | |
| T4 | Live-привязка: время с начала налива | ⏳ ожидает | | | |
| T5 | Gate и упреждение | ⏳ ожидает | | | |
| T6 | Резервный компонент при некондиционной партии | ⏳ ожидает | | | |
| T7 | Объяснение, отказ, готовность к внедрению | ⏳ ожидает | | | |
| T8 | UI парка со стадиями | 📤 передано фронту | | | |
| T9 | Перефиксация эталонов, отчёт «было / стало» | ⏳ ожидает | | | |

## Этап 5. Доказательства на итоговой модели

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| E1 | Команды исследований с `DEFAULT_BUDGET`, отпечаток | ⏳ ожидает | | | |
| E2 | Оценщик другой структуры | ⏳ ожидает | | | |
| E3 | Строгий same-input агентов | ⏳ ожидает | | | |
| E4 | Пересчитать benchmark и оценки | ⏳ ожидает | | | |
| S3 | QA 21.09: `neftecode selfcheck` на фиксированных срезах (владелец добавил 21.09) | ⏳ ожидает | | | |

## Этап 6. Пробелы ТЗ

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| G1 | ЛИМС/ПАК/ВАК приоритет | ⏸ заблокировано | | решение владельца: отказ (README) | |
| G2 | ВСГ/сырьё как управляющая переменная | ⏸ заблокировано | | решение владельца: отказ (README) | |
| G3 | Тяжесть режима: ресурс катализатора | ⏳ ожидает | | | |
| G4 | Парето-фронт допустимых планов | ⏳ ожидает | | | |
| G5 | Аудит `source` у каждого числа | ⏳ ожидает | | | |
| G6 | Журнал обмена агентов в карточке (сервер) | ⏳ ожидает | | | |
| G6-фронт | Отображение журнала | 📤 передано фронту | | | |
| G7 | Replay из архива, offline UI | ⏸ заблокировано | | решение владельца: не берём | |
| G8 | Перекалибровка 6,01% vs 5% | ⏸ заблокировано | | решение владельца: закреплено как ограничение | |

## Этап 7. Документация и процесс

| ID | Задача | Статус | Коммит | Проверка | Дата |
|---|---|---|---|---|---|
| D1 | Обновить `architecture.md`, `code-tour.md`, `services.md`, `defence.md`, `solution.md`, README | ⏳ ожидает | | | |
| D2 | Новое определение «готово» в `context/README.md` | ⏳ ожидает | | | |
| D3 | Чек-лист регулярного аудита против ТЗ | ⏳ ожидает | | | |
| N3 | Подготовка к защите по β + вводная фраза `defence.md` (владелец добавил 21.09) | ⏳ ожидает | | | |
| S4 | QA 21.09: упаковка данных в архив сдачи (не в публичный git), описание периодов (владелец добавил 21.09) | ⏳ ожидает | | | |
| S5 | QA 21.09: презентация решения на основе `defence.md` (владелец добавил 21.09) | ⏳ ожидает | | | |

## Передано фронту (сводка)

Z3, O1-фронт, O2-фронт, O3, O4-подпись Stop после A7, T8, G6-фронт — критерии готовности
и контракт см. `context/frontend-handoff.md` (создаётся по мере готовности контракта).
