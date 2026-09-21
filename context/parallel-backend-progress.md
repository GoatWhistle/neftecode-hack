# Прогресс backend-пакета B1–B6

Ветка: `task/audit-backend`. База: `3e6f2aff98d1dac39fbc8ca2b01c1d4626035a72`.
Frontend и общие журналы не изменяются.

| ID | Статус | Коммит | Проверка | Результат и ограничения |
|---|---|---|---|---|
| B1 | ✅ выполнено | `a2c2d96` | `LLM_PROVIDER=scripted uv run pytest -q tests/infrastructure/test_snapshots.py tests/architecture/test_path_equivalence.py tests/services/test_decision_service.py tests/services/test_gateway_service.py` — 30 passed, 1 skipped | При пригодных источниках недоступный обязательный прогноз даёт явный отказ; старый срез без `forecast_no_pak` требует пересборки; полный срез с `frozen_pak` сохраняет `catboost_no_pak` и hold; `both_broken` остаётся отказом по данным. |
| B2 | ✅ выполнено | `3f633c7` | `LLM_PROVIDER=scripted uv run pytest -q tests/agentic/test_safety.py` — 39 passed | Ограничения и veto сохраняются после сбоев оркестратора, resolve, release и guard. Повторный сбой recovery даёт отказ с трассой, а не запрещённый legacy-план. |
| B3 | ✅ выполнено | `91a168d` | Целевые demo/service/snapshot/agentic/path-тесты — 75 passed, 1 skipped | Общий цикл перенесён в application-use-case `AdviseUnderConditions`; composition и decision-service форматируют/транспортируют его результат. Совместимые `run_demo_decision`, `Demo.run`, `GatewayService._decide` не содержат второго алгоритма. |
| B4 | ✅ выполнено | `ff58f8d` | `LLM_PROVIDER=scripted uv run pytest -q tests/presentation/test_server.py tests/services/test_gateway_service.py tests/services/test_common.py` — 49 passed | Gateway обслуживает `/api/stream` настоящим SSE. Норма и содержательный отказ завершаются `screen/end`, инфраструктурный сбой — `failed`; serve и stack используют тот же формат кадров. |
| B5 | ✅ выполнено | текущий коммит | Целевые cancellation/SSE/safety-тесты — 14 passed, 39 deselected | Закрытие потока отменяет дальнейший поиск и новые LLM-вызовы; тестовый worker освобождается менее чем за 0,5 с. Уже отправленный внешний запрос нельзя остановить на стороне провайдера: после возврата ответ отбрасывается и новые вызовы не начинаются. |
| B6 | ⏳ ожидает | — | — | — |
