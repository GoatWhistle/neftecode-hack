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
    expect(row(cmp, "refusal").b).toBe("нет допустимого плана");
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

describe("скрытые изменения входов", () => {
  const withParts = (name: string, parts: Record<string, unknown>, fingerprint: string) => {
    const base = record(name);
    return {
      ...base,
      meta: { ...base.meta!, input_fingerprint: fingerprint, input_parts: { scenario_sha256: "s1", snapshot_sha256: "p1", model: null, ...parts } }
    } as typeof base;
  };

  it("одинаковые запрошенные условия, но другая конфигурация сценария не объявляются совпадающими", () => {
    const cmp = comparePair(withParts("risk", {}, "f1"), withParts("risk", { scenario_sha256: "s2" }, "f2"));
    expect(cmp.inputDiff).toEqual([]);
    expect(cmp.identicalInputs).toBe(false);
    expect(cmp.hiddenChanges.length).toBeGreaterThan(0);
  });

  it("изменение содержимого среза при том же ключе замечено", () => {
    const cmp = comparePair(withParts("risk", {}, "f1"), withParts("risk", { snapshot_sha256: "p2" }, "f2"));
    expect(cmp.hiddenChanges.join(" ")).toContain("срез");
  });

  it("одинаковые части и отпечаток — скрытых изменений нет", () => {
    const cmp = comparePair(withParts("risk", {}, "f1"), withParts("risk", {}, "f1"));
    expect(cmp.hiddenChanges).toEqual([]);
    expect(cmp.identicalInputs).toBe(true);
  });
});


describe("объяснение различий входов", () => {
  type Meta = NonNullable<ReturnType<typeof record>["meta"]>;
  const withMeta = (base: ReturnType<typeof record>, patch: (meta: Meta) => Meta) =>
    ({ ...base, meta: patch(structuredClone(base.meta!)) }) as typeof base;
  const parts = (meta: Meta) => meta.input_parts as Record<string, unknown>;
  const sameParts = { scenario_sha256: "s1", snapshot_sha256: "p1", model: { response_model_sha256: "m", training_fingerprint: "t" },
    response_binding: { beta_mgkg_per_c: -0.42 }, severity_profile: "severity-profile/1:x" };

  it("обычный what-if (только отказ источника) — без ложного «необъяснённого» предупреждения", () => {
    const a = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fa", input_parts: { ...sameParts } }));
    const b = withMeta(record("risk-frozen-pak", { fault: "both_broken" }), (m) => ({
      ...m, input_fingerprint: "fb", conditions_requested: { ...m.conditions_requested!, fault: "both_broken" },
      input_parts: { ...sameParts, response_binding: { beta_mgkg_per_c: null }, severity_profile: null } }));
    const cmp = comparePair(a, b);
    expect(cmp.inputDiff.map((item) => item.key)).toEqual(["fault"]);
    expect(cmp.hiddenChanges).toEqual([]);
    expect(cmp.unexplained).toBeNull();
  });

  it("смена сцены (сценарий и срез по запросу) не объявляется изменением «при том же ключе»", () => {
    const a = withMeta(record("normal", { scenario: "baseline", snapshot: "20260105-080000" }),
      (m) => ({ ...m, input_fingerprint: "fa", input_parts: { ...sameParts } }));
    const b = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fb",
      input_parts: { ...sameParts, scenario_sha256: "s2", snapshot_sha256: "p2", response_binding: { beta_mgkg_per_c: -0.3 } } }));
    const cmp = comparePair(a, b);
    expect(cmp.inputDiff.map((item) => item.key)).toEqual(expect.arrayContaining(["scenario", "snapshot"]));
    expect(cmp.hiddenChanges).toEqual([]);
    expect(cmp.unexplained).toBeNull();
    expect(cmp.incomparable.map((item) => item.key)).toContain("snapshot");
  });

  it("тот же ключ среза с другим snapshot_sha256 виден и делает показатели несопоставимыми", () => {
    const a = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fa", input_parts: { ...sameParts } }));
    const b = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fb", input_parts: { ...sameParts, snapshot_sha256: "p2" } }));
    const cmp = comparePair(a, b);
    expect(cmp.inputDiff).toEqual([]);
    expect(cmp.hiddenChanges.join(" ")).toContain("при том же ключе среза");
    expect(cmp.identicalInputs).toBe(false);
    expect(cmp.incomparable.map((item) => item.key)).toContain("snapshot");
    expect(row(cmp, "cost").delta).toBeNull();
  });

  it("замена модели под теми же условиями видна, дельты не считаются", () => {
    const a = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fa", input_parts: { ...sameParts } }));
    const b = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fb",
      model: { response_model_sha256: "other", training_fingerprint: m.model!.training_fingerprint },
      input_parts: { ...sameParts, model: { response_model_sha256: "other", training_fingerprint: "t" } } }));
    const cmp = comparePair(a, b);
    expect(cmp.hiddenChanges.join(" ")).toContain("Модель отклика заменена");
    expect(cmp.incomparable.map((item) => item.key)).toContain("model");
    expect(row(cmp, "production").delta).toBeNull();
  });

  it("неизвестная версия модели (null в полях) не считается совпадающей", () => {
    const a = record("risk");
    const b = withMeta(record("risk"), (m) => ({ ...m, model: { response_model_sha256: null, training_fingerprint: null } }));
    const cmp = comparePair(a, b);
    expect(cmp.incomparable.map((item) => item.key)).toContain("model");
    expect(row(cmp, "cost").delta).toBeNull();
  });

  it("части отпечатка сравниваются по содержимому, а не по порядку ключей", () => {
    const a = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "f",
      input_parts: { ...sameParts, model: { response_model_sha256: "m", training_fingerprint: "t" } } }));
    const b = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "f",
      input_parts: { ...sameParts, model: { training_fingerprint: "t", response_model_sha256: "m" } } }));
    const cmp = comparePair(a, b);
    expect(cmp.hiddenChanges).toEqual([]);
    expect(cmp.identicalInputs).toBe(true);
  });

  it("производные части при тех же условиях — изменение под теми же ключами; остальное — необъяснённое", () => {
    const a = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fa", input_parts: { ...sameParts } }));
    const b = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fb",
      input_parts: { ...sameParts, severity_profile: "severity-profile/1:y" } }));
    expect(comparePair(a, b).hiddenChanges.join(" ")).toContain("Профиль тяжести");
    const c = withMeta(record("risk"), (m) => ({ ...m, input_fingerprint: "fc", input_parts: { ...sameParts } }));
    const cmp = comparePair(a, c);
    expect(cmp.hiddenChanges).toEqual([]);
    expect(cmp.unexplained).toContain("не объясняют");
    expect(parts(c.meta!).snapshot_sha256).toBe("p1");
  });
});
