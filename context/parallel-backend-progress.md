# Прогресс backend-пакета B1–B6

Ветка: `task/audit-backend`. База: `3e6f2aff98d1dac39fbc8ca2b01c1d4626035a72`.
Frontend и общие журналы не изменяются.

| ID | Статус | Коммит | Проверка | Результат и ограничения |
|---|---|---|---|---|
| B1 | ✅ выполнено | `a2c2d96` | `LLM_PROVIDER=scripted uv run pytest -q tests/infrastructure/test_snapshots.py tests/architecture/test_path_equivalence.py tests/services/test_decision_service.py tests/services/test_gateway_service.py` — 30 passed, 1 skipped | При пригодных источниках недоступный обязательный прогноз даёт явный отказ; старый срез без `forecast_no_pak` требует пересборки; полный срез с `frozen_pak` сохраняет `catboost_no_pak` и hold; `both_broken` остаётся отказом по данным. |
| B2 | ✅ выполнено | `3f633c7` | `LLM_PROVIDER=scripted uv run pytest -q tests/agentic/test_safety.py` — 39 passed | Ограничения и veto сохраняются после сбоев оркестратора, resolve, release и guard. Повторный сбой recovery даёт отказ с трассой, а не запрещённый legacy-план. |
| B3 | ✅ выполнено | текущий коммит | Целевые demo/service/snapshot/agentic/path-тесты — 75 passed, 1 skipped | Общий цикл перенесён в application-use-case `AdviseUnderConditions`; composition и decision-service форматируют/транспортируют его результат. Совместимые `run_demo_decision`, `Demo.run`, `GatewayService._decide` не содержат второго алгоритма. |
| B4 | ⏳ ожидает | — | — | — |
| B5 | ⏳ ожидает | — | — | — |
| B6 | ⏳ ожидает | — | — | — |
