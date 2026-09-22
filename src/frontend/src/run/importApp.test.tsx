import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { buildProtocol, canonicalJson, serializeProtocol } from "./protocol";
import { sha256Hex } from "./sha256";
import { record } from "./testRecords";

const options = {
  state: "loading", message: "", scenario: "sour_crude", snapshot: "20260724-030000", scenarios: ["sour_crude"],
  faults: ["healthy", "both_broken"], snapshots: [{ key: "20260724-030000", title: "риск" }],
  defaults: { crude_sulfur_wt_pct: 1.95, product_sulfur_mgkg: 10, product_t95_c: 360, product_cetane_number: 51,
    throughput_tph: 100, tanks: [{ id: "main", inventory: 4000, on_demand: false, available: true }] }
};

type Packet = { content: Record<string, Record<string, unknown> | null | boolean>; checksum: { value: string } };

function packet(): Packet {
  const a = record("risk", {}, "Риск");
  const b = record("risk-reserve-off", { tank: "reserve", tank_available: "0" }, "Вариант B");
  return JSON.parse(serializeProtocol(buildProtocol(a, b))) as Packet;
}

function resign(value: Packet): string {
  value.checksum.value = sha256Hex(canonicalJson(value.content));
  return JSON.stringify(value);
}

function upload(text: string): void {
  const file = new File([text], "protocol.json", { type: "application/json" });
  fireEvent.change(screen.getByLabelText("Файл протокола решения"), { target: { files: [file] } });
}

const calls = (spy: ReturnType<typeof vi.fn>) => spy.mock.calls.map(([url]) => String(url));

import { catalog as historyCatalog } from "../features/history-explorer/fixtures";

describe("импорт протокола в смонтированное приложение", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn(async (url: string) =>
      String(url).startsWith("/api/options")
        ? new Response(JSON.stringify(options), { status: 200 })
        : String(url).startsWith("/api/history")
          ? new Response(JSON.stringify(historyCatalog), { status: 200 })
          : new Response(null, { status: 500 }));
    vi.stubGlobal("fetch", fetchSpy);
    window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener() {},
      removeEventListener() {} })) as unknown as typeof window.matchMedia;
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} unobserve() {} });
    HTMLElement.prototype.scrollIntoView = () => {};
  });

  afterEach(() => vi.unstubAllGlobals());

  async function openGood(): Promise<void> {
    render(<App />);
    await screen.findByRole("button", { name: "Открыть запись" });
    upload(serializeProtocol(buildProtocol(record("risk", {}, "Риск"),
      record("risk-reserve-off", { tank: "reserve", tank_available: "0" }, "Вариант B"))));
    await waitFor(() => expect(screen.getByLabelText("Открыта сохранённая запись")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: /Ответ изменился/ })).toBeInTheDocument();
  }

  it("после запуска показывает и фокусирует итог, подробная схема не заслоняет ответ", async () => {
    const payload = record("risk").payload;
    const prior = fetchSpy.getMockImplementation() as (url: string) => Promise<Response>;
    fetchSpy.mockImplementation(async (url: string) => String(url).startsWith("/api/stream")
      ? new Response(`event: screen\ndata: ${JSON.stringify({ payload, elapsed_ms: 120 })}\n\n`,
        { headers: { "Content-Type": "text/event-stream" } })
      : prior(url));
    render(<App />);
    const start = await screen.findByRole("button", { name: "Запустить расчёт" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Расширенные условия" }));
    expect(document.querySelector("#map-drawer-input")).toBeInTheDocument();
    fireEvent.click(start);
    expect(await screen.findByText(/Расчёт завершён/)).toBeVisible();
    await waitFor(() => expect(screen.getByLabelText("Результат запуска")).toHaveFocus());
    expect(screen.getByLabelText("Результат запуска").compareDocumentPosition(
      document.querySelector(".calculation-map")!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.getByText("Предложен сценарный план")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Расширенные условия" }));
    expect(document.querySelector("#map-drawer-input")).toBeInTheDocument();
  });

  it("смена момента не переписывает дату показанного ответа и просит перезапуск", async () => {
    await openGood();
    expect(screen.queryByText(/Выбран другой момент/)).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: /Изменить/ })[0]!);
    fireEvent.click(await screen.findByRole("button", { name: /Срез из поставки/ }));
    fireEvent.click(screen.getByRole("button", { name: "Использовать этот момент" }));
    const notice = await screen.findByText(/Выбран другой момент — запустите расчёт/);
    expect(notice.closest("p")?.textContent).toMatch(/относится\s+к 24 июля 2026 · 03:00/);
    expect(screen.queryByRole("tab", { name: "Готовые эпизоды" })).toBeNull();
    expect(calls(fetchSpy).some((url) => url.startsWith("/api/decide") || url.startsWith("/api/stream"))).toBe(false);
  });

  function screenState(): string {
    return [
      screen.getByLabelText("Открыта сохранённая запись").textContent,
      screen.getByRole("heading", { name: /Ответ изменился/ }).textContent,
      screen.getByText("B · Вариант B").textContent
    ].join("|");
  }

  it("структурно плохой пакет с верной контрольной суммой отклоняется, прежние A/B и экран сохранены", async () => {
    await openGood();
    const before = screenState();
    const bad = packet();
    delete (bad.content.b as Record<string, unknown>).form;
    upload(resign(bad));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/запись B.*form/);
    expect(screenState()).toBe(before);
    expect(calls(fetchSpy).some((url) => url.startsWith("/api/decide") || url.startsWith("/api/stream"))).toBe(false);
  });

  it("повреждённая контрольная сумма и невалидный слот A/B дают понятную ошибку без смены экрана", async () => {
    await openGood();
    const before = screenState();
    upload(serializeProtocol(buildProtocol(record("risk"), null)).replace("recommend_scenario", "recommend_scenarix"));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Контрольная сумма не совпала/);
    expect(screenState()).toBe(before);

    const falsy = packet();
    falsy.content.a = false;
    upload(resign(falsy));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/запись A/));
    expect(screenState()).toBe(before);

    const badType = packet();
    ((badType.content.a as { payload: { decision: { tradeoff: { points: Array<Record<string, unknown>> } } } })
      .payload.decision.tradeoff.points[0]!).production_t = "много";
    upload(resign(badType));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/tradeoff\.points\[0\]\.production_t/));
    expect(screenState()).toBe(before);
    expect(calls(fetchSpy).some((url) => url.startsWith("/api/decide") || url.startsWith("/api/stream"))).toBe(false);
  });
});
