# Фикстуры паспорта доказательств

- `research-summary-final-2026.json` — вывод сборщика без правки вручную:
  `uv run python -m neftecode.infrastructure.artifacts.research_summary --root . --out <этот файл>`.
  Совпадение со сборщиком проверяет `tests/infrastructure/test_research_summary.py`, совпадение чисел
  с `research/forecast/final-2026.json` — `EvidencePassport.test.tsx`.
- `live-agentic-2026-09-17.json` — блок `decision.agentic` живого прогона zai/glm-5.3-flash из
  `artifacts/agent-live-full-20260917.json` без изменений (artifacts не в Git). В тесте он
  подставляется в payload нормы 05.01 — это композиция двух настоящих ответов, а не запись сервера.
  Вариант fallback получен в тесте явной мутацией и так помечен.
