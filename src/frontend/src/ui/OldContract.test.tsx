import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActionBlock } from "./Verdict";
import type { ScreenPayload } from "../types";
// Тестовая мутация (НЕ запись сервера): decide-baseline-2026-01-05.json с вырезанными
// plan_origin/chain/confidence_kind — эмулирует старый payload до O1/N2/N1, см. fixtures/README.md.
import oldFixture from "../fixtures/decide-baseline-2026-01-05.mutated-old-contract.json";

const payload = oldFixture as unknown as ScreenPayload;

describe("F6 — старый payload без plan_origin/chain не ломается и не выдумывает управляемость", () => {
  it("без plan_origin показывает «не определено», а не выдуманный derived", () => {
    render(<ActionBlock payload={payload} action={payload.decision.immediate_action!} />);
    const avt = screen.getByText("Температура на выходе печи АВТ").closest(".final__control");
    expect(avt!.querySelector(".origin")!.className).toContain("origin--absent");
  });
});
