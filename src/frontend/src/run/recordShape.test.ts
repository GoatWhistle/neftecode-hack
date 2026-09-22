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
});
