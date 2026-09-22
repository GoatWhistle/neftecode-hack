import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { fixture } from "../../run/testRecords";
import { payloadShape } from "../../run/recordShape";
import type { Agentic, Choice, ScreenPayload } from "../../types";
import { ChoicePanel } from "./ChoicePanel";
import sour from "./fixtures/choice-sour_crude.json";
import baseline from "./fixtures/choice-baseline.json";
import refused from "./fixtures/choice-no_feasible.json";
import vetoed from "./fixtures/choice-agent-veto.json";

type Real = { decision_id: string; status: string; choice: Choice; agentic?: Partial<Agentic> };

function payloadWith(real: Real, agentic: Partial<Agentic> | null = null): ScreenPayload {
  const base = fixture("normal");
  return {
    ...base,
    decision: {
      ...base.decision, status: real.status, decision_id: real.decision_id, choice: real.choice,
      agentic: agentic ? ({ ...(base.decision.agentic ?? {}), ...agentic } as Agentic) : base.decision.agentic
    }
  };
}

describe("почему этот вариант (P2)", () => {
  it("старая запись без choice честно сообщает об отсутствии связей", () => {
    render(<ChoicePanel payload={fixture("normal")} />);
    expect(screen.getByText(/не сохранена: запись сделана до её появления/)).toBeInTheDocument();
  });

  it("реальный выход backend проходит валидацию импорта", () => {
    for (const real of [sour, baseline, refused, vetoed] as Real[]) {
      expect(() => payloadShape(payloadWith(real), "payload")).not.toThrow();
    }
  });

  it("дешёвый недопустимый вариант показан исключённым, клик открывает проверки этого запуска", () => {
    const real = sour as Real;
    render(<ChoicePanel payload={payloadWith(real)} />);
    const cheaper = screen.getByRole("article", { name: new RegExp(`Дешевле из рассмотренных: ${real.choice.cheaper_id}`) });
    expect(within(cheaper).getByText("исключён")).toBeInTheDocument();
    const reason = within(cheaper).getByRole("button", { name: /нарушен базовый Gate/ });
    expect(reason).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(reason);
    expect(reason).toHaveAttribute("aria-expanded", "true");
    const table = within(cheaper).getByRole("table");
    expect(within(table).getByText(real.decision_id)).toBeInTheDocument();
    const ref = real.choice.candidates.find((c) => c.candidate_id === real.choice.cheaper_id)!.reasons[0]!.evidence![0]!;
    expect(within(table).getByText(ref.constraint_id!)).toBeInTheDocument();
    // hold исключён Gate — это не «безопасный режим»
    const hold = screen.getByRole("article", { name: /Сохранить режим: hold/ });
    expect(within(hold).getByText("исключён")).toBeInTheDocument();
  });

  it("политика минимального выигрыша названа как определившая итог", () => {
    render(<ChoicePanel payload={payloadWith(baseline as Real)} />);
    const stages = screen.getByRole("list", { name: "Что определило итог" });
    expect(within(stages).getByText(/политика выбора/)).toBeInTheDocument();
    expect(screen.getByRole("article", { name: /Выбран: сохранить режим: hold/ })).toBeInTheDocument();
  });

  it("отказ: стадия, доказанная невозможность и кандидаты с причинами", () => {
    render(<ChoicePanel payload={payloadWith(refused as Real)} onChangeCondition={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Почему решение не выдано" })).toBeInTheDocument();
    expect(screen.getByText(/невозможность подтверждена расчётом/)).toBeInTheDocument();
    expect(screen.getAllByRole("article").length).toBe((refused as Real).choice.candidates.length);
  });

  it("вето агента на выбор ядра показано как установленное влияние", () => {
    render(<ChoicePanel payload={payloadWith(vetoed as Real)} />);
    expect(screen.getByText(/Влияние на выбор установлено/)).toBeInTheDocument();
    const stages = screen.getByRole("list", { name: "Что определило итог" });
    expect(within(stages).getByText(/агентный этап/)).toBeInTheDocument();
  });

  it("таймаут провайдера не называется предметной невозможностью", () => {
    render(<ChoicePanel payload={payloadWith(sour as Real, { outcome: "fallback", fallback_reason: "provider_timeout" })} />);
    expect(screen.getByText(/provider_timeout/)).toBeInTheDocument();
    expect(screen.getByText(/не доказательство того, что допустимого решения нет/)).toBeInTheDocument();
  });

  it("«Изменить условие» только открывает what-if и не меняет выбор", () => {
    const onChange = vi.fn();
    const payload = payloadWith(sour as Real);
    const before = JSON.stringify(payload.decision.choice);
    render(<ChoicePanel payload={payload} onChangeCondition={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Изменить условие" }));
    fireEvent.click(screen.getAllByRole("button", { name: /нарушен базовый Gate/ })[0]!);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(payload.decision.choice)).toBe(before);
  });

  it("некорректный choice при импорте отклоняется до смены экрана", () => {
    const real = structuredClone(sour) as Real;
    (real.choice.candidates[0] as unknown as Record<string, unknown>).verdict = "maybe";
    expect(() => payloadShape(payloadWith(real), "payload")).toThrow(/choice\.candidates\[0\]\.verdict/);
  });
});
