import raw from "./fixtures/research-summary-final-2026.json";
import { validateResearchSummary } from "./research";
import type { ResearchSummary } from "./research";

/**
 * Сводка исследования, собранная `research_summary.py` из research/forecast и приложенная к
 * сборке фронтенда. Совпадение с артефактом проверяет pytest
 * (test_committed_frontend_fixture_matches_builder). Это результат исследования прогноза серы
 * потока, а не доказательство качества модели конкретной записи.
 */
export const BUILD_RESEARCH: ResearchSummary = validateResearchSummary(raw);
