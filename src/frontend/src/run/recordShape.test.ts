import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { payloadShape, runMetaShape, ShapeError } from "./recordShape";
import { parseProtocol } from "./protocol";

const dir = (...parts: string[]) => resolve(process.cwd(), "src/fixtures", ...parts);
const payloads = [
  ...readdirSync(dir("pair")).map((name) => dir("pair", name)),
  ...readdirSync(dir()).filter((name) => name.startsWith("decide-") && !name.includes("mutated")).map((name) => dir(name))
];

describe("контракт записи прогона на реальных ответах сервера", () => {
  it.each(payloads)("%s проходит структурную проверку", (path) => {
    const payload = JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;
    expect(() => payloadShape(payload, "payload")).not.toThrow();
    if (payload.run_meta) expect(() => runMetaShape(payload.run_meta, "meta")).not.toThrow();
  });

  it("сохранённые экспорты нашей версии схемы открываются", () => {
    const text = readFileSync(dir("protocol-export-2026-09-22.json"), "utf-8");
    const parsed = parseProtocol(text);
    expect(parsed.a?.payload.decision.status).toBe("recommend_scenario");
    expect(parsed.b?.payload.decision.status).toBe("refuse");
  });

  it("нарушение типа указывает путь поля", () => {
    const payload = JSON.parse(readFileSync(dir("pair", "risk.json"), "utf-8")) as { decision: { selected_plan: unknown } };
    payload.decision.selected_plan = { plan_id: "x", intent: "y", changes: "1", steps: [] };
    expect(() => payloadShape(payload, "payload")).toThrow(ShapeError);
    expect(() => payloadShape(payload, "payload")).toThrow(/payload\.decision\.selected_plan\.changes/);
  });

  it("старая запись без consequences (поле отсутствует) проходит проверку", () => {
    const payload = JSON.parse(readFileSync(dir("pair", "risk.json"), "utf-8")) as Record<string, unknown>;
    expect((payload.decision as Record<string, unknown>).consequences).toBeUndefined();
    expect(() => payloadShape(payload, "payload")).not.toThrow();
  });

  it("некорректное новое поле consequences отклоняется до смены экрана", () => {
    const payload = JSON.parse(readFileSync(dir("pair", "risk.json"), "utf-8")) as { decision: Record<string, unknown> };
    payload.decision.consequences = {
      version: 1, selected_id: "hold", horizon_hours: 3, step_hours: 0.5,
      series: [{
        limit_id: "sulfur_mgkg", quality: "sulfur_mgkg", unit: "мг/кг", direction: "max",
        limit: { value: "10" /* строка вместо числа */, source: "given" },
        candidates: { selected: { candidate_id: "hold", points: [] } }
      }],
      applicability: { selected: [] },
      hold: { available: true, candidate_id: "hold", source: "selected_is_hold", reason: null },
      note: "test"
    };
    expect(() => payloadShape(payload, "payload")).toThrow(ShapeError);
    expect(() => payloadShape(payload, "payload")).toThrow(/consequences/);
  });

  it("неконечное время отклика в событиях consequences отклоняется", () => {
    const payload = JSON.parse(readFileSync(dir("pair", "risk.json"), "utf-8")) as { decision: Record<string, unknown> };
    payload.decision.consequences = {
      version: 1, selected_id: "c1", horizon_hours: 3, step_hours: 0.5, series: [],
      applicability: { selected: [] },
      hold: { available: false, candidate_id: null, source: null, reason: "нет" }, note: "test",
      events: { selected: [{ kind: "control", origin: "plan", t: 0, response_t: null, lag_hours: 1, lag_source: "given" }] }
    };
    expect(() => payloadShape(payload, "payload")).toThrow(/consequences\.events\.selected\[0\]\.response_t/);
  });
});
