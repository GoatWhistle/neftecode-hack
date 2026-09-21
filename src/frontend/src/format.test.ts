import { describe, expect, it } from "vitest";
import { MISSING, isNumber, num, percent, withUnit } from "./format";

describe("num", () => {
  it("округляет и форматирует по-русски", () => {
    expect(num(1234.5678, 2)).toBe("1 234,57");
  });

  it("возвращает прочерк для отсутствующего значения", () => {
    expect(num(null)).toBe("—");
    expect(num(undefined)).toBe("—");
    expect(num(Number.NaN)).toBe("—");
  });
});

describe("withUnit", () => {
  it("добавляет единицу только к реальному числу", () => {
    expect(withUnit(30, "кг/т", 0)).toBe("30 кг/т");
    expect(withUnit(null, "кг/т")).toBe("—");
  });

  it("не путает нулевое значение с отсутствующим", () => {
    expect(withUnit(0, "кг/т", 0)).toBe("0 кг/т");
  });
});

describe("percent", () => {
  it("переводит долю в проценты", () => {
    expect(percent(0.03, 1)).toBe("3 %");
  });
});

describe("isNumber", () => {
  it("отличает число от MISSING-строки", () => {
    expect(isNumber(MISSING)).toBe(false);
    expect(isNumber(0)).toBe(true);
  });
});
