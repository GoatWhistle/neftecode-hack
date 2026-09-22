import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fixture } from "../../run/testRecords";
import type { Consequences as ConsequencesData, ScreenPayload } from "../../types";
import { Consequences } from "./Consequences";
import { applicabilityMoments, worstStatus } from "./model";

const SAMPLE: ConsequencesData = {
  version: 1, selected_id: "c0001", horizon_hours: 3, step_hours: 0.5,
  series: [
    {
      limit_id: "sulfur_mgkg", quality: "sulfur_mgkg", unit: "мг/кг", direction: "max",
      limit: { value: 10, source: "given" },
      candidates: {
        selected: {
          candidate_id: "c0001",
          points: [
            { t: 0, value: 5, status: "pass" }, { t: 0.5, value: 7, status: "pass" },
            { t: 1, value: null, status: "unknown" }, { t: 1.5, value: 12, status: "fail" }
          ]
        },
        hold: {
          candidate_id: "hold",
          points: [{ t: 0, value: 5, status: "pass" }, { t: 0.5, value: 5, status: "pass" },
            { t: 1, value: 5, status: "pass" }, { t: 1.5, value: 5, status: "pass" }]
        }
      }
    },
    {
      limit_id: "t95_c", quality: "t95_c", unit: "°C", direction: "max",
      limit: { value: 360, source: "given" },
      candidates: { selected: { candidate_id: "c0001", points: [{ t: 0, value: 340, status: "pass" }] } }
    }
  ],
  applicability: { selected: [{ t: 0, value: "in_region" }, { t: 1.5, value: "out_of_region" }] },
  hold: { available: true, candidate_id: "hold", source: "search_pool", reason: null },
  note: "Модельные последствия, не доказанный эффект на заводе."
};

function withConsequences(consequences: ConsequencesData | null): ScreenPayload {
  const payload = fixture("normal");
  return { ...payload, decision: { ...payload.decision, consequences } };
}

describe("последствия во времени", () => {
  it("старая запись без поля consequences показывает предупреждение, а не пустой график", () => {
    render(<Consequences payload={fixture("normal")} />);
    expect(screen.getByText(/Траектория не сохранена/)).toBeInTheDocument();
  });

  it("отказ: consequences явно null — отдельное сообщение", () => {
    render(<Consequences payload={withConsequences(null)} />);
    expect(screen.getByText(/решение не выдано/)).toBeInTheDocument();
  });

  it("рисует выбранный план и hold, разрывает ряд на пропуске и предупреждает про экстраполяцию", () => {
    render(<Consequences payload={withConsequences(SAMPLE)} />);
    // показатель с нарушением выбран по умолчанию
    expect(screen.getByRole("tab", { name: /sulfur_mgkg/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/вне откалиброванной области/)).toBeInTheDocument();
    expect(screen.getAllByText(/1,5 ч/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText(/нет числа/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /t95_c/ }));
    expect(screen.getByRole("tab", { name: /t95_c/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/не посчитан/)).toBeInTheDocument(); // у t95_c нет hold
  });

  it("если hold недоступен — явно объясняет причину, не рисует придуманную линию", () => {
    const noHold: ConsequencesData = {
      ...SAMPLE,
      series: SAMPLE.series.map((s) => ({ ...s, candidates: { selected: s.candidates.selected } })),
      hold: { available: false, candidate_id: null, source: null, reason: "план hold не построен для этого сценария" }
    };
    render(<Consequences payload={withConsequences(noHold)} />);
    expect(screen.getByText(/Сравнение с сохранением режима недоступно/)).toBeInTheDocument();
    expect(screen.getByText(/план hold не построен/)).toBeInTheDocument();
  });

  it("пустой ряд — «нет оценки», а не пройденная проверка", () => {
    expect(worstStatus([])).toBe("unknown");
    const empty: ConsequencesData = {
      ...SAMPLE,
      series: [{ ...SAMPLE.series[1]!, candidates: { selected: { candidate_id: "c0001", points: [] } } }]
    };
    render(<Consequences payload={withConsequences(empty)} />);
    expect(screen.getByRole("tab", { name: /t95_c.*нет оценки/ })).toBeInTheDocument();
  });

  it("неизвестная применимость не называется экстраполяцией; hold показан отдельно", () => {
    expect(applicabilityMoments([
      { t: 0, value: "in_region" }, { t: 1, value: "unknown" }, { t: 2, value: "out_of_region" }
    ])).toEqual({ outside: [2], unknown: [1] });
    const unknownOnly: ConsequencesData = {
      ...SAMPLE,
      applicability: {
        selected: [{ t: 0, value: "in_region" }, { t: 1, value: "unknown" }],
        hold: [{ t: 0.5, value: "out_of_region" }]
      }
    };
    render(<Consequences payload={withConsequences(unknownOnly)} />);
    expect(screen.getByText(/Выбранный план: применимость модели не установлена на 1 ч/)).toBeInTheDocument();
    expect(screen.queryByText(/Выбранный план: модель отклика вне/)).toBeNull();
    expect(screen.getByText(/Сохранить режим: вне откалиброванной области на 0,5 ч/)).toBeInTheDocument();
  });

  it("показывает моменты действия и отклика из payload, а без них — честное отсутствие", () => {
    const withEvents: ConsequencesData = {
      ...SAMPLE,
      events: {
        selected: [{
          kind: "control", origin: "plan", t: 0.5, response_t: 1.5, lag_hours: 1, lag_source: "given",
          stage: "hydrotreating", controls: { ht_reactor_inlet_temp_c: 342 }
        }]
      },
      events_note: "Отклик относится к потоку после своей стадии."
    };
    const { container, unmount } = render(<Consequences payload={withConsequences(withEvents)} />);
    expect(screen.getByText(/гидроочистка: ht_reactor_inlet_temp_c → 342/)).toBeInTheDocument();
    expect(screen.getByText(/О1: 1,5 ч \(запаздывание 1 ч, given\)/)).toBeInTheDocument();
    expect(container.querySelectorAll(".cns__event--action").length).toBe(1);
    expect(container.querySelectorAll(".cns__event--response").length).toBe(1);
    unmount();
    render(<Consequences payload={withConsequences(SAMPLE)} />);
    expect(screen.getByText(/Моменты действий и отклика в этой записи не сохранены/)).toBeInTheDocument();
  });
});
