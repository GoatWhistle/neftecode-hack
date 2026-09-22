import { catalog } from "./fixtures";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HistoryExplorer } from "./HistoryExplorer";
import type { HistoryCatalog } from "./types";


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

it("произвольный момент не округляется, набор времени и обзор не выбирают сцену", () => {
  const onSelect = vi.fn(), onOverview = vi.fn();
  const full: HistoryCatalog = { ...catalog, arbitrary: { available: true, reason: null },
    coverage: { start: "2023-01-01T00:00:00", end: "2026-08-07T00:00:00", model_valid_from: "2026-01-01" } };
  render(<HistoryExplorer catalog={full} selection={null} onSelect={onSelect} onOverview={onOverview} />);
  fireEvent.change(screen.getByLabelText("Местное время решения"), { target: { value: "2026-01-05T08:07:13" } });
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Выбрать точный момент" }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith({ kind: "moment", requested_at: "2026-01-05T08:07:13" });
  fireEvent.change(screen.getByLabelText("Начало периода"), { target: { value: "2026-01-05T08:00" } });
  fireEvent.change(screen.getByLabelText("Конец периода"), { target: { value: "2026-01-05T12:00" } });
  fireEvent.click(screen.getByText("Обзор периода без расчёта решения"));
  fireEvent.click(screen.getByRole("button", { name: "Показать наблюдения" }));
  expect(onOverview).toHaveBeenCalledExactlyOnceWith("2026-01-05T08:00", "2026-01-05T12:00");
  expect(onSelect).toHaveBeenCalledTimes(1);
});

it("вне покрытия и до появления модели момент не предлагается", () => {
  render(<HistoryExplorer catalog={{ ...catalog, arbitrary: { available: true, reason: null },
    coverage: { start: "2023-01-01T00:00:00", end: "2026-08-07T00:00:00", model_valid_from: "2026-01-01" } }}
    selection={null} onSelect={vi.fn()} />);
  for (const value of ["2025-12-31T23:59", "2026-08-07T00:01"]) {
    fireEvent.change(screen.getByLabelText("Местное время решения"), { target: { value } });
    expect(screen.getByRole("button", { name: "Выбрать точный момент" }).hasAttribute("disabled")).toBe(true);
  }
});

it("сохраняет секунды нижней границы и показывает измеренную телеметрию", () => {
  const first = catalog.items[0]!;
  render(<HistoryExplorer catalog={{ ...catalog, arbitrary: { available: true, reason: null },
    items: [{ ...first, measurements: { "ht.T6": { value: 367.8, time: "2026-07-03T11:10:00", age_min: 0 } } }],
    coverage: { start: "2026-07-03T08:07:13", end: "2026-08-07T00:00:00", model_valid_from: "2026-01-01" } }}
    selection={null} onSelect={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Местное время решения"), { target: { value: "2026-07-03T08:07" } });
  expect(screen.getByRole("button", { name: "Выбрать точный момент" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByText(/ht.T6: 367,8/)).toBeTruthy();
});
