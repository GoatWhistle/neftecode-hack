import { describe, expect, it } from "vitest";
import { additiveDoseKgPerT, doseDigits, doseText } from "./format";

describe("additiveDoseKgPerT", () => {
  it("умножает долю на 1000, а не показывает долю как кг/т", () => {
    expect(additiveDoseKgPerT(0.03)).toBe(30);
  });

  it("не путает нулевую дозу с отсутствующей", () => {
    expect(additiveDoseKgPerT(0)).toBe(0);
    expect(additiveDoseKgPerT(null)).toBe(null);
    expect(additiveDoseKgPerT(undefined)).toBe(null);
  });
});

describe("doseText", () => {
  it("0 → 0 кг/т", () => {
    expect(doseText(0)).toBe("0 кг/т");
  });

  it("0.03 (доля) → 30 кг/т", () => {
    expect(doseText(0.03)).toBe("30 кг/т");
  });

  it("отсутствует → прочерк, а не 0", () => {
    expect(doseText(null)).toBe("—");
    expect(doseText(undefined)).toBe("—");
  });

  it("малая ненулевая доза не округляется до неотличимого от нуля", () => {
    // 0.00003 доли = 0.03 кг/т — при одном знаке после запятой выглядело бы как 0,0
    expect(doseText(0.00003)).not.toBe("0 кг/т");
    expect(doseText(0.00003)).toContain("0,03");
  });
});

describe("doseDigits", () => {
  it("подбирает точность так, чтобы малая ненулевая доза не исчезала", () => {
    expect(doseDigits(0)).toBe(0);
    expect(doseDigits(30)).toBe(1);
    expect(doseDigits(0.5)).toBe(2);
    expect(doseDigits(0.03)).toBe(3);
    expect(doseDigits(0.003)).toBe(4);
  });
});
