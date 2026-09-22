import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HistoryExplorer } from "./HistoryExplorer";
import type { HistoryCatalog } from "./types";

export const catalog: HistoryCatalog = {
  schema_version: "history.v1", timezone: "source-local", grid_minutes: 10,
  total: 1, next_offset: null, snapshot_coverage: null,
  arbitrary: { available: false, reason: "нет task/" }, note: "Наблюдавшиеся условия",
  items: [{ snapshot: "20260703-111000", at: "2026-07-03T11:10:00", label: "Срез из поставки",
    synthetic_edits: [], facts: { lab_value: null, pak_value: 8, telemetry_missing_fraction: null,
      lab_sample_time: null, lab_available_time: null, pak_sample_time: null },
    measurements: {}, provenance: { model_fingerprint: null, source_rules_fingerprint: null } }]
};

describe("исторический каталог", () => {
  it("фильтр не запускает ничего, выбор передаёт точный срез", () => {
    const onSelect = vi.fn();
    render(<HistoryExplorer catalog={catalog} selection={null} onSelect={onSelect} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "нет такого" } });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText("Подходящих срезов нет.")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "2026-07" } });
    fireEvent.click(screen.getByRole("button", { name: /Срез из поставки/ }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith({ kind: "snapshot", snapshot: "20260703-111000", requested_at: "2026-07-03T11:10:00" });
  });
  it("дата результата принадлежит записи даже при ошибке и новом выборе", () => {
    render(<HistoryExplorer catalog={catalog} selection={null} onSelect={vi.fn()}
      recordTime="2026-01-01T12:00:00" error="Момент недоступен" disabled />);
    expect(screen.getByText("2026-01-01 12:00:00")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Момент недоступен");
    expect(screen.getByRole("button", { name: /Срез из поставки/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Доступны только готовые срезы/)).toBeTruthy();
  });
});
