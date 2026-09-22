import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { comparePair } from "../run/pair";
import { fixture, record } from "../run/testRecords";
import { WhatIf, quickChangeOf } from "../whatif/WhatIf";
import { PairCompare } from "./PairCompare";
import { TradeoffMapView } from "./TradeoffMap";
import { OperatorAnswer } from "../ui/OperatorAnswer";

describe("карта компромиссов", () => {
  it("показывает вырожденный фронт и не придумывает альтернатив; клик объясняет, но выбор не меняет", () => {
    const payload = fixture("risk");
    render(<TradeoffMapView payload={payload} />);
    expect(screen.getByText(/Фронт выродился в одну точку/)).toBeInTheDocument();
    const selectedId = payload.decision.tradeoff!.selected_id!;
    const other = payload.decision.tradeoff!.points.find((p) => !p.selected)!;
    fireEvent.click(screen.getAllByRole("button", { name: other.candidate_id })[0]!);
    expect(screen.getByText(/Клик по точке только объясняет/)).toBeInTheDocument();
    expect(payload.decision.tradeoff!.selected_id).toBe(selectedId);
    expect(screen.getAllByRole("table").length).toBe(1);
  });

  it("при отказе карта не строится", () => {
    render(<TradeoffMapView payload={fixture("risk-reserve-off")} />);
    expect(screen.getByText(/Карта компромиссов не строится/)).toBeInTheDocument();
  });
});

describe("парное сравнение и что-если", () => {
  it("рендерит заголовок, отличия входов и предупреждения несопоставимости", () => {
    const cmp = comparePair(record("risk"), record("risk-reserve-off", { tank: "reserve", tank_available: "0" }));
    render(<PairCompare comparison={cmp} labelA="A" labelB="B" />);
    expect(screen.getByText(/Ответ изменился/)).toBeInTheDocument();
    expect(screen.getByText(/Доступность резервуара/)).toBeInTheDocument();
  });

  it("быстрое изменение строит патч только из отличий от A", () => {
    const base = record("risk").form as never;
    const tanks = [{ id: "main", available: true, inventory: 4000 }, { id: "reserve", available: true, inventory: 500 }];
    const draft = { fault: "healthy", tank: "reserve", available: "0", throughput: "" };
    const change = quickChangeOf({ ...(base as object), fault: "healthy", tank: "", tank_available: "", throughput_tph: "" } as never, draft, tanks);
    expect(change.patch).toMatchObject({ tank: "reserve", tank_available: "0" });
    expect(change.summary).toHaveLength(1);
    const none = quickChangeOf({ ...(base as object), fault: "healthy", tank: "", tank_available: "", throughput_tph: "" } as never,
      { fault: "healthy", tank: "main", available: "1", throughput: "" }, tanks);
    expect(none.summary).toEqual([]);
  });

  it("без закреплённого A предлагает закрепить; кнопка недоступна без результата", () => {
    const onPin = vi.fn();
    render(<WhatIf pinned={null} hasResult={false} running={false} options={null} onPin={onPin} onUnpin={() => undefined} onRun={() => undefined} />);
    expect(screen.getByRole("button", { name: "Закрепить для сравнения" })).toBeDisabled();
  });

  it("с закреплённым A запускает B только при изменении", () => {
    const onRun = vi.fn();
    render(<WhatIf pinned={record("risk")} hasResult running={false} options={null} onPin={() => undefined} onUnpin={() => undefined} onRun={onRun} />);
    const run = screen.getByRole("button", { name: /Пересчитать/ });
    expect(run).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/\d|по сценарию/), { target: { value: "80" } });
    expect(run).toBeEnabled();
    fireEvent.click(run);
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ throughput_tph: "80" }), expect.anything());
  });
});

describe("ответ оператору", () => {
  it("отказ не предписывает сохранять непроверенный режим", () => {
    render(<OperatorAnswer payload={fixture("bad-data")} />);
    expect(screen.queryByText(/Уставки не менять/)).toBeNull();
    expect(screen.getByText("Решение не выдано")).toBeVisible();
    expect(screen.getByText(/Для повторного расчёта нужно: свежий лабораторный/)).toBeVisible();
  });

  it("рецепт в массовых процентах", () => {
    render(<OperatorAnswer payload={fixture("risk")} />);
    expect(screen.getByText(/% масс\./)).toBeInTheDocument();
  });
});
