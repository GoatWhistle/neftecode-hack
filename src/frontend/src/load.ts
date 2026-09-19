import type { ApiPayload, ScreenPayload } from "./types";
import { isError, isScreen } from "./types";
import { FIXTURE } from "./data/fixture";

export type Origin = "fixture" | "server" | "file";

export interface Loaded {
  screen: ScreenPayload;
  origin: Origin;
  detail: string;
}

export interface LoadFailure {
  message: string;
}

export const FIXTURE_LOADED: Loaded = {
  screen: FIXTURE,
  origin: "fixture",
  detail: "встроенный замороженный прогон сценария baseline"
};

function describe(payload: ScreenPayload): string {
  return `сценарий ${payload.decision.scenario_id ?? "—"}, решение ${payload.decision.decision_id ?? "—"}`;
}

export async function fetchScenarios(): Promise<string[]> {
  const response = await fetch("/api/options");
  if (!response.ok) throw new Error(`сервер ответил ${response.status}`);
  const data = (await response.json()) as { scenarios?: string[] };
  return data.scenarios ?? [];
}

export async function fetchDecision(scenario: string): Promise<Loaded> {
  const query = scenario ? `?scenario=${encodeURIComponent(scenario)}` : "";
  const response = await fetch(`/api/decide${query}`);
  if (!response.ok) throw new Error(`сервер ответил ${response.status}`);
  const payload = (await response.json()) as ApiPayload;
  if (isError(payload)) throw new Error(payload.message);
  if (!isScreen(payload)) throw new Error("сервер ещё считает решение, повторите запрос");
  return { screen: payload, origin: "server", detail: describe(payload) };
}

export async function readFilePayload(file: File): Promise<Loaded> {
  const text = await file.text();
  const parsed = JSON.parse(text) as ApiPayload & { decision?: unknown };
  if (isScreen(parsed)) {
    return { screen: parsed, origin: "file", detail: `${file.name}: ${describe(parsed)}` };
  }
  throw new Error(
    `Файл ${file.name} не похож на экран решения: нужен payload с полями state, decision и explanation`
  );
}
