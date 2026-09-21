import { describe, expect, it } from "vitest";
import { planDiff } from "./PlanDiff";
import type { Alternative, PlanStep } from "../types";

const baseline: PlanStep = {
  time_hours: 0,
  controls: {},
  recipe: {},
  throughput_tph: 100,
  additive_dose: 0
};

function alt(additive_dose: number | null): Alternative {
  return {
    candidate_id: "c1",
    production_t: 100,
    cost_per_tonne: 1,
    severity_index: 0,
    changes: 1,
    why_not: "",
    additive_dose
  };
}

describe("planDiff — доза присадки в кг/т, не в доле", () => {
  it("показывает разницу доз в кг/т компонентов, а не как сырую долю", () => {
    const entries = planDiff(alt(0.03), baseline, {});
    const dose = entries.find((e) => e.key === "additive");
    expect(dose).toBeTruthy();
    expect(dose!.unit).toBe("кг/т");
    expect(dose!.from).toBe(0);
    expect(dose!.to).toBe(30);
  });

  it("не показывает разницу, когда доза совпадает (в пределах округления доли)", () => {
    const entries = planDiff(alt(0.0001), baseline, {});
    expect(entries.find((e) => e.key === "additive")).toBeUndefined();
  });

  it("подбирает точность так, что малая ненулевая разница не исчезает до 0", () => {
    const entries = planDiff(alt(0.00005), { ...baseline, additive_dose: 0.03 }, {});
    const dose = entries.find((e) => e.key === "additive");
    expect(dose).toBeTruthy();
    expect(dose!.digits).toBeGreaterThanOrEqual(3);
  });
});
