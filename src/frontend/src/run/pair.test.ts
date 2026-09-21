import { describe, expect, it } from "vitest";
import { comparePair } from "./pair";
import { buildRecord } from "./record";
import { fixture, form, record, tapeFor } from "./testRecords";

const row = (cmp: ReturnType<typeof comparePair>, id: string) => cmp.rows.find((item) => item.id === id)!;

describe("парное сравнение", () => {
  it("изменение входа переводит решение в отказ, а дельта не считается из отсутствующих значений", () => {
    const cmp = comparePair(record("risk"), record("risk-reserve-off", { tank: "reserve", tank_available: "0" }));
    expect(cmp.answerChanged).toBe(true);
    expect(cmp.headline).toContain("Ответ изменился");
    expect(row(cmp, "status").a).not.toBe(row(cmp, "status").b);
    expect(row(cmp, "production").b).toBe("неизвестно");
    expect(row(cmp, "production").delta).toBeNull();
    expect(row(cmp, "cost").delta).toBeNull();
    expect(row(cmp, "severity").delta).toBeNull();
    expect(row(cmp, "refusal").b).toBe("no_feasible_plan");
    expect(row(cmp, "needs").b).toContain("сера основного компонента");
    expect(cmp.inputDiff.map((item) => item.key)).toContain("tank_available");
    expect(cmp.identicalInputs).toBe(false);
  });

  it("смена доступности источника меняет решение; отличающийся вход перечислен", () => {
    const cmp = comparePair(record("risk"), record("risk-frozen-pak", { fault: "frozen_pak" }));
    expect(cmp.answerChanged).toBe(true);
    expect(cmp.inputDiff).toEqual([expect.objectContaining({ key: "fault", b: expect.stringContaining("завис") })]);
  });

  it("пара без изменения ответа честно показана как «не изменился»", () => {
    const cmp = comparePair(record("risk"), record("risk-stale-lab", { fault: "stale_lab" }));
    expect(cmp.answerChanged).toBe(false);
    expect(cmp.headline).toContain("не изменил");
    expect(cmp.rows.filter((r) => ["status", "plan", "changes"].includes(r.id)).every((r) => r.changed === false)).toBe(true);
    expect(cmp.inputDiff.map((item) => item.key)).toEqual(["fault"]);
  });

  it("одинаковые входы дают одинаковый отпечаток и нулевую дельту", () => {
    const a = record("risk");
    const cmp = comparePair(a, record("risk"));
    expect(cmp.identicalInputs).toBe(true);
    expect(cmp.inputDiff).toEqual([]);
    expect(row(cmp, "cost").delta).toBe("0 у. е./т");
    expect(row(cmp, "severity").delta).toBe("0");
  });

  it("несовпадающий срез и горизонт помечаются несопоставимыми и не дают дельты", () => {
    const base = fixture("risk");
    const other = fixture("normal");
    other.run_meta = { ...other.run_meta!, horizon_hours: 6 };
    const cmp = comparePair(
      buildRecord({ payload: base, form: form(), query: null, label: "A", tape: tapeFor(base), durationMs: 1 }),
      buildRecord({ payload: other, form: form({ scenario: "baseline" }), query: null, label: "B", tape: tapeFor(other), durationMs: 1 })
    );
    const keys = cmp.incomparable.map((item) => item.key);
    expect(keys).toEqual(expect.arrayContaining(["snapshot", "horizon"]));
    expect(row(cmp, "production").delta).toBeNull();
    expect(row(cmp, "production").note).toContain("несопоставимы");
    expect(row(cmp, "cost").delta).toBeNull();
  });

  it("неизвестные метаданные не заменяются нулями и делают модель несопоставимой", () => {
    const a = fixture("risk");
    const b = fixture("risk");
    delete (b as { run_meta?: unknown }).run_meta;
    const cmp = comparePair(
      buildRecord({ payload: a, form: form(), query: null, label: "A", tape: null, durationMs: null }),
      buildRecord({ payload: b, form: form(), query: null, label: "B", tape: null, durationMs: null })
    );
    expect(cmp.inputsKnown).toBe(false);
    expect(cmp.identicalInputs).toBeNull();
    expect(cmp.incomparable.map((i) => i.key)).toEqual(expect.arrayContaining(["model", "provider"]));
  });

  it("изменение только присадки видно строкой изменений и в мг/кг-единицах кг/т", () => {
    const a = fixture("risk");
    const b = structuredClone(a);
    b.decision.immediate_action = { ...b.decision.immediate_action!, additive_dose: 0.03 };
    const cmp = comparePair(
      buildRecord({ payload: a, form: form(), query: null, label: "A", tape: null, durationMs: null }),
      buildRecord({ payload: b, form: form(), query: null, label: "B", tape: null, durationMs: null })
    );
    expect(row(cmp, "changes").changed).toBe(true);
    expect(row(cmp, "changes").b).toContain("Доза присадки");
    expect(row(cmp, "changes").b).toContain("30 кг/т");
  });

  it("предупреждает о вариативности живой языковой модели", () => {
    const a = record("risk");
    const b = fixture("risk");
    b.run_meta = { ...b.run_meta!, provider: { ...b.run_meta!.provider!, provider: "zai", model: "glm", deterministic_policy: false } };
    const cmp = comparePair(a, buildRecord({ payload: b, form: form(), query: null, label: "B", tape: null, durationMs: null }));
    expect(cmp.notes.join(" ")).toContain("вариативность");
    expect(cmp.incomparable.map((i) => i.key)).toContain("provider");
  });

  it("сообщает, если введённое значение сервер заменил", () => {
    const b = record("risk", { throughput_tph: "77" });
    const cmp = comparePair(record("risk"), b);
    expect(cmp.notApplied.join(" ")).toContain("сервер применил");
  });

  it("закреплённая запись A неизменяема", () => {
    const a = record("risk");
    expect(Object.isFrozen(a)).toBe(true);
    expect(() => {
      (a.payload.decision as { status: string }).status = "changed";
    }).toThrow();
  });
});
