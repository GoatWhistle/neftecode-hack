# Прогресс backend-пакета B1–B6

Ветка: `task/audit-backend`. База: `3e6f2aff98d1dac39fbc8ca2b01c1d4626035a72`.
Frontend и общие журналы не изменяются.

| ID | Статус | Коммит | Проверка | Результат и ограничения |
|---|---|---|---|---|
| B1 | ✅ выполнено | текущий коммит | `LLM_PROVIDER=scripted uv run pytest -q tests/infrastructure/test_snapshots.py tests/architecture/test_path_equivalence.py tests/services/test_decision_service.py tests/services/test_gateway_service.py` — 30 passed, 1 skipped | При пригодных источниках недоступный обязательный прогноз даёт явный отказ; старый срез без `forecast_no_pak` требует пересборки; полный срез с `frozen_pak` сохраняет `catboost_no_pak` и hold; `both_broken` остаётся отказом по данным. |
| B2 | ⏳ ожидает | — | — | — |
| B3 | ⏳ ожидает | — | — | — |
| B4 | ⏳ ожидает | — | — | — |
| B5 | ⏳ ожидает | — | — | — |
| B6 | ⏳ ожидает | — | — | — |
