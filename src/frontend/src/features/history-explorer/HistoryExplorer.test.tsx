import { catalog } from "./fixtures";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HistoryExplorer } from "./HistoryExplorer";
import { MomentSummary } from "./MomentSummary";
import { longMoment, momentKey, momentOf, shortMoment } from "./moment";
import type { HistoryCatalog } from "./types";

const full: HistoryCatalog = { ...catalog, arbitrary: { available: true, reason: null },
  coverage: { start: "2023-01-01T00:00:00", end: "2026-08-07T00:00:00", model_valid_from: "2026-01-01" } };

function tab(name: string): void {
  fireEvent.click(screen.getByRole("tab", { name }));
}

describe("готовые эпизоды", () => {
  it("открываются первыми; клик по строке — предпросмотр, применение — отдельной кнопкой", () => {
    const onSelect = vi.fn();
    render(<HistoryExplorer catalog={catalog} selection={null} onSelect={onSelect} />);
    expect(screen.getByRole("tab", { name: "Готовые эпизоды" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "нет такого" } });
    expect(screen.getByText("Подходящих эпизодов нет.")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "03 июл" } });
    fireEvent.click(screen.getByRole("button", { name: /Срез из поставки/ }));
    expect(onSelect).not.toHaveBeenCalled();
    const detail = screen.getByRole("region", { name: /Подробности/ });
    expect(detail.textContent).toContain("03 июля 2026 · 11:10");
    expect(detail.textContent).toContain("Исторический срез");
    expect(detail.textContent).toContain("8 ppm");
    fireEvent.click(screen.getByRole("button", { name: "Использовать этот момент" }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith({ kind: "snapshot", snapshot: "20260703-111000", requested_at: "2026-07-03T11:10:00" });
  });

  it("синтетический срез помечен явно, уже выбранный не применяется повторно", () => {
    const first = catalog.items[0]!;
    render(<HistoryExplorer catalog={{ ...catalog, items: [{ ...first, synthetic_edits: ["ПАК заморожен"] }] }}
      selection={null} current="20260703-111000" onSelect={vi.fn()} />);
    expect(screen.getByText("С искусственными изменениями")).toBeTruthy();
    expect(screen.getByText(/Изменено: ПАК заморожен/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Этот момент уже выбран" }).hasAttribute("disabled")).toBe(true);
  });

  it("ошибка видна, запуск во время расчёта заблокирован, без task/ доступны только эпизоды", () => {
    render(<HistoryExplorer catalog={catalog} selection={null} onSelect={vi.fn()} error="Момент недоступен" disabled />);
    expect(screen.getByRole("alert").textContent).toBe("Момент недоступен");
    expect(screen.getByRole("button", { name: "Использовать этот момент" }).hasAttribute("disabled")).toBe(true);
    tab("Точная дата");
    expect(screen.getByText(/Доступны только готовые эпизоды/)).toBeTruthy();
  });

  it("сведения об измерениях и происхождении свёрнуты в подробностях", () => {
    const first = catalog.items[0]!;
    render(<HistoryExplorer catalog={{ ...catalog, items: [{ ...first,
      measurements: { "ht.T6": { value: 367.8, time: "2026-07-03T11:10:00", age_min: 0 } } }] }}
      selection={null} onSelect={vi.fn()} />);
    expect(screen.getByText("Измерения и происхождение")).toBeTruthy();
    expect(screen.getByText(/ht.T6: 367,8 °C/)).toBeTruthy();
  });
});

describe("точная дата и обзор периода", () => {
  it("момент не округляется, ввод сам по себе ничего не выбирает", () => {
    const onSelect = vi.fn();
    render(<HistoryExplorer catalog={full} selection={null} onSelect={onSelect} />);
    tab("Точная дата");
    expect(screen.getByText("Используются только измерения, доступные к выбранному моменту.")).toBeTruthy();
    expect(screen.getByText("Как выбираются данные")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Местное время решения"), { target: { value: "2026-01-05T08:07:13" } });
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Выбрать точный момент" }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith({ kind: "moment", requested_at: "2026-01-05T08:07:13" });
  });

  it("вне покрытия и до появления модели момент не предлагается", () => {
    render(<HistoryExplorer catalog={full} selection={null} onSelect={vi.fn()} />);
    tab("Точная дата");
    for (const value of ["2025-12-31T23:59", "2026-08-07T00:01"]) {
      fireEvent.change(screen.getByLabelText("Местное время решения"), { target: { value } });
      expect(screen.getByRole("button", { name: "Выбрать точный момент" }).hasAttribute("disabled")).toBe(true);
    }
  });

  it("сохраняет секунды нижней границы", () => {
    render(<HistoryExplorer catalog={{ ...full, coverage: { start: "2026-07-03T08:07:13",
      end: "2026-08-07T00:00:00", model_valid_from: "2026-01-01" } }} selection={null} onSelect={vi.fn()} />);
    tab("Точная дата");
    fireEvent.change(screen.getByLabelText("Местное время решения"), { target: { value: "2026-07-03T08:07" } });
    expect(screen.getByRole("button", { name: "Выбрать точный момент" }).hasAttribute("disabled")).toBe(true);
  });

  it("обзор периода — просмотр без расчёта и без выбора момента", () => {
    const onSelect = vi.fn(), onOverview = vi.fn();
    render(<HistoryExplorer catalog={full} selection={null} onSelect={onSelect} onOverview={onOverview} />);
    tab("Обзор периода");
    expect(screen.getByText("Просмотр данных без расчёта рекомендации.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Начало периода"), { target: { value: "2026-01-05T08:00" } });
    fireEvent.change(screen.getByLabelText("Конец периода"), { target: { value: "2026-01-05T12:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Показать наблюдения" }));
    expect(onOverview).toHaveBeenCalledExactlyOnceWith("2026-01-05T08:00", "2026-01-05T12:00");
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("строка «Данные для расчёта»", () => {
  it("дата читается без сдвига часового пояса, из ключа среза и из точного момента", () => {
    expect(longMoment("2026-01-05T08:00:00")).toBe("05 января 2026 · 08:00");
    expect(longMoment("20260416-101000")).toBe("16 апреля 2026 · 10:10");
    expect(longMoment("2026-01-05T08:07:13")).toBe("05 января 2026 · 08:07:13");
    expect(shortMoment("2026-01-09T01:10:00")).toBe("09 янв · 01:10");
  });

  it("срез берёт название эпизода из каталога, момент — отдельный ключ", () => {
    const fromCatalog = momentOf({ snapshot: "20260703-111000" }, catalog, []);
    expect(fromCatalog).toEqual({ key: "20260703-111000", at: "2026-07-03T11:10:00", kind: "snapshot", label: "Срез из поставки" });
    expect(momentOf({ snapshot: "20260105-080000" }, null, [{ key: "20260105-080000", title: "Норма" }])?.label).toBe("Норма");
    expect(momentKey({ snapshot: "x", at: "2026-01-05T08:07" })).not.toBe(momentKey({ snapshot: "x" }));
  });

  it("показывает дату, тип и эпизод; «Изменить» только открывает выбор", () => {
    const onToggle = vi.fn();
    render(<MomentSummary moment={{ key: "k", at: "2026-01-05T08:00:00", kind: "snapshot", label: "Норма" }}
      open={false} onToggle={onToggle} />);
    expect(screen.getByText("05 января 2026 · 08:00")).toBeTruthy();
    expect(screen.getByText("Исторический срез")).toBeTruthy();
    expect(screen.getByText("эпизод «Норма»")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Изменить/ }));
    expect(onToggle).toHaveBeenCalledOnce();
  });
});
