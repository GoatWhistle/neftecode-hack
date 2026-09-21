import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActionBlock } from "./Verdict";
import type { ScreenPayload } from "../types";
import fixture from "../fixtures/decide-baseline-2026-01-05.json";

// Фикстура — реальный /api/decide, срез 05.01.2026 (см. fixtures/README.md).
const payload = fixture as unknown as ScreenPayload;

describe("ActionBlock — origin из plan_origin, не жёсткий derived (F3/O1)", () => {
  it("подписывает АВТ как scenario, а не derived", () => {
    render(<ActionBlock payload={payload} action={payload.decision.immediate_action!} />);
    const avt = screen.getByText("Температура на выходе печи АВТ").closest(".final__control");
    expect(avt).toBeTruthy();
    expect(avt!.querySelector(".origin")!.className).toContain("origin--scenario");
  });

  it("подписывает T6 (ход ГО) как measured — реальное измерение с установки", () => {
    render(<ActionBlock payload={payload} action={payload.decision.immediate_action!} />);
    const ht = screen.getByText("Температура на входе реактора ГО").closest(".final__control");
    expect(ht).toBeTruthy();
    expect(ht!.querySelector(".origin")!.className).toContain("origin--measured");
  });
});
