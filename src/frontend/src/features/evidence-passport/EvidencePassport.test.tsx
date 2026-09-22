import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { Agentic, ScreenPayload } from "../../types";
import type { RunState } from "../../run/types";
import { EMPTY_RUN } from "../../run/types";
import { hydrateRun, recordInfoOf } from "../../run/hydrate";
import { parseProtocol } from "../../run/protocol";
import { fixture } from "../../run/testRecords";
import { num, percent } from "../../format";
import { EvidencePassport } from "./EvidencePassport";
import { constraintKey, passportModel, UNKNOWN } from "./model";
import type { PassportRow } from "./model";
import { modelLink, researchSlot, ResearchSummaryError, validateResearchSummary } from "./research";
import summaryJson from "./fixtures/research-summary-final-2026.json";
// Реальный ответ сервера без run_meta (снят до появления provenance, см. src/fixtures/README.md).
import baselineOld from "../../fixtures/decide-baseline-2026-01-05.json";
// Реальный scripted-прогон, где агенты консультировались и одно ограничение подтверждено.
import sourCrude from "../../fixtures/decide-sour-crude-agents.json";
// decision.agentic живого прогона zai/glm-5.3-flash 17.09 без изменений (artifacts/agent-live-full-20260917.json).
import liveAgentic from "./fixtures/live-agentic-2026-09-17.json";

const root = resolve(process.cwd(), "../..");
const final = JSON.parse(readFileSync(resolve(root, "research/forecast/final-2026.json"), "utf-8"));
const research = validateResearchSummary(summaryJson);

function clone<T>(value: T): T {
  return structuredClone(value);
}

function done(payload: ScreenPayload, patch: Partial<RunState> = {}): RunState {
  return { ...EMPTY_RUN, status: "done", payload, live: true, serverMs: 5200, ...patch };
}

/** Композиция двух настоящих ответов: payload нормы 05.01 + agentic живого прогона. Не запись сервера. */
function livePayload(): ScreenPayload {
  const payload = clone(fixture("normal"));
  payload.decision.agentic = clone(liveAgentic.agentic) as unknown as Agentic;
  return payload;
}

function rowOf(rows: PassportRow[], key: string): PassportRow {
  const found = rows.find((item) => item.key === key);
  if (!found) throw new Error(`нет строки ${key}`);
  return found;
}

describe("P3 — вход: данные и применимость", () => {
  it("берёт модель и код из run_meta записи, а не из настроек сервера", () => {
    const payload = fixture("normal");
    const model = passportModel({ run: done(payload) })!;
    expect(rowOf(model.input.rows, "model").value).toBe(payload.run_meta!.model!.training_fingerprint!.slice(0, 12));
    expect(rowOf(model.input.rows, "decision-time").value).toBe(payload.decision_time);
    expect(rowOf(model.input.rows, "readiness").tone).toBe("warn");
  });

  it("старый ответ без run_meta: версия неизвестна, не подставлена", () => {
    const model = passportModel({ run: done(baselineOld as unknown as ScreenPayload) })!;
    expect(rowOf(model.input.rows, "model").value).toBe(UNKNOWN);
    expect(rowOf(model.input.rows, "code").value).toBe(UNKNOWN);
    expect(model.input.notes.join(" ")).toContain("нет run_meta");
  });

  it("показывает происхождение управляющих величин и возраст источников", () => {
    const model = passportModel({ run: done(fixture("normal")) })!;
    const controls = model.input.rows.filter((item) => item.key.startsWith("control-"));
    expect(controls.length).toBeGreaterThan(0);
    expect(controls.some((item) => item.value.includes("измерение"))).toBe(true);
    expect(model.input.rows.some((item) => item.key.startsWith("source-") && item.value.includes("ч"))).toBe(true);
  });

  it("отказ по данным: непригодный источник отмечен, агенты не запускались", () => {
    const model = passportModel({ run: done(fixture("bad-data")) })!;
    expect(model.input.rows.filter((item) => item.key.startsWith("source-")).some((item) => item.tone === "warn")).toBe(true);
    expect(model.agents.mode).toBe("skipped");
    expect(model.agents.roles).toHaveLength(0);
  });
});

describe("P3 — проверено: числа из артефакта", () => {
  it("сводка совпадает с research/forecast/final-2026.json без округления", () => {
    expect(research.baseline.mae_mgkg).toBe(final.baseline.mae_mgkg);
    expect(research.winner.mae_mgkg).toBe(final.winner.mae_mgkg);
    expect(research.winner.exceed_upper).toBe(final.winner.exceed_upper);
    expect(research.baseline.exceed_upper).toBe(final.baseline.exceed_upper);
    expect(research.paired_mae_difference.ci95_mgkg).toEqual(final.paired_mae_winner_minus_baseline.ci95);
    expect(research.paired_targets).toBe(final.paired_available_targets);
    expect(research.total_targets).toBe(final.total_targets);
  });

  it("6.01% превышений не выдаётся за достигнутую цель 5%", () => {
    render(<EvidencePassport run={done(fixture("normal"))} research={research} />);
    const part = screen.getByRole("region", { name: "Проверено" });
    expect(within(part).getByText(new RegExp(`${num(final.winner.mae_mgkg, 3)}`))).toBeInTheDocument();
    const exceed = within(part).getByText(new RegExp(percent(final.winner.exceed_upper, 2)));
    expect(exceed.textContent).toContain("не достигнута");
    expect(exceed.textContent).not.toMatch(/цель ≤ 5 % достигнута/);
    expect(part.textContent).toContain("не описывает качество товарной смеси");
  });

  it("другая модель записи: исследовательский результат, не доказательство текущей модели", () => {
    const payload = fixture("normal");
    expect(modelLink(research, payload.run_meta)).toBe("other");
    const model = passportModel({ run: done(payload), research })!;
    expect(model.verified.notes[0]).toContain("не доказательство качества текущей модели");
  });

  it("совпадение отпечатка с проверенной моделью признаётся только по записи", () => {
    const payload = clone(fixture("normal"));
    payload.run_meta!.model!.training_fingerprint = research.model_link.evaluation_fingerprint;
    expect(modelLink(research, payload.run_meta)).toBe("evaluated");
    expect(modelLink(research, null)).toBe("unknown");
  });

  it("без сводки раздел честно пуст", () => {
    const model = passportModel({ run: done(fixture("normal")) })!;
    expect(model.verified.available).toBe(false);
    expect(model.verified.notes[0]).toContain("не передана");
  });
});

describe("P3 — адаптер импорта сводки", () => {
  it("неизвестная версия схемы отклоняется", () => {
    expect(() => validateResearchSummary({ ...summaryJson, schema: "neftecode.research-summary/2" }))
      .toThrow(ResearchSummaryError);
  });

  it("неизвестное и неконечное число отклоняются", () => {
    const missing = clone(summaryJson) as Record<string, unknown>;
    (missing.winner as Record<string, unknown>).mae_mgkg = null;
    expect(() => validateResearchSummary(missing)).toThrow(/неизвестное или неконечное/);
    const infinite = clone(summaryJson) as Record<string, unknown>;
    (infinite.baseline as Record<string, unknown>).rmse_mgkg = Number.POSITIVE_INFINITY;
    expect(() => validateResearchSummary(infinite)).toThrow(ResearchSummaryError);
  });

  it("отметка цели, противоречащая числам, отклоняется", () => {
    const lied = clone(summaryJson) as Record<string, unknown>;
    (lied.goal as Record<string, unknown>).met_by_winner = true;
    expect(() => validateResearchSummary(lied)).toThrow(/противоречит/);
  });

  it("старый протокол без поля сводки даёт null, запись открывается и паспорт строится", () => {
    const text = readFileSync(resolve(process.cwd(), "src/fixtures/protocol-export-2026-09-22.json"), "utf-8");
    const parsed = parseProtocol(text);
    expect(researchSlot((parsed.protocol.content as unknown as Record<string, unknown>)["research"])).toBeNull();
    const run = hydrateRun(parsed.a!, recordInfoOf(parsed.a!, null));
    const model = passportModel({ run })!;
    expect(model.mark.origin).toBe("record");
    expect(model.mark.text).toContain(parsed.a!.run_id);
    expect(rowOf(model.input.rows, "model").value).toBe(parsed.a!.meta!.model!.training_fingerprint!.slice(0, 12));
  });
});

describe("P3 — агенты", () => {
  it("live: вызовы, время, токены из записи; стоимость неизвестна, не ноль", () => {
    const model = passportModel({ run: done(livePayload()) })!;
    expect(model.agents.mode).toBe("live");
    expect(rowOf(model.agents.rows, "mode").value).toContain("glm-5.3-flash");
    expect(rowOf(model.agents.rows, "calls").value).toMatch(/^1 из 12/);
    expect(rowOf(model.agents.rows, "time").value).toContain("29,6 с");
    expect(rowOf(model.agents.rows, "tokens").value).toContain((4174).toLocaleString("ru-RU"));
    expect(rowOf(model.agents.rows, "cost").value).toBe(UNKNOWN);
    expect(model.agents.notes.join(" ")).toContain("Это не ноль");
    expect(rowOf(model.agents.rows, "outcome").value).toContain("выбор не изменился");
  });

  it("scripted: подтверждённое ограничение без трассы — влияние не установлено", () => {
    const payload = sourCrude as unknown as ScreenPayload;
    const model = passportModel({ run: done(payload) })!;
    expect(model.agents.mode).toBe("scripted");
    expect(rowOf(model.agents.rows, "tokens").value).toContain("scripted не расходует токены");
    const applied = model.agents.constraints.filter((line) => line.applied);
    expect(applied).toHaveLength(1);
    expect(applied[0]!.influence.text).toContain("влияние на выбор не установлено");
    expect(model.agents.notes.join(" ")).toContain("улучшение не утверждается");
  });

  it("доказанная связь подключается ссылкой, а не счётчиком", () => {
    const payload = sourCrude as unknown as ScreenPayload;
    const key = constraintKey(payload.decision.agentic!.constraints_applied![0]!);
    render(<EvidencePassport run={done(payload)} influenceRefs={{ [key]: { text: "исключён c0041", href: "#trace-c0041" } }} />);
    expect(screen.getByRole("link", { name: "исключён c0041" })).toHaveAttribute("href", "#trace-c0041");
  });

  it("мнение отклонено: ограничение не применено, роль помечена", () => {
    const payload = clone(sourCrude) as unknown as ScreenPayload;
    payload.decision.agentic!.opinions![0]!.valid = false;
    const model = passportModel({ run: done(payload) })!;
    const quality = model.agents.roles.find((role) => role.key === "quality")!;
    expect(quality.validity).toBe("мнение отклонено как невалидное");
    expect(quality.invalid).toBe(true);
    const line = model.agents.constraints.find((item) => item.role === "quality")!;
    expect(line.applied).toBe(false);
    expect(line.influence.text).toContain("мнение невалидно");
  });

  it("fallback: причина сбоя показана, исход не выдан за выбор", () => {
    const payload = livePayload();
    const agentic = payload.decision.agentic!;
    agentic.outcome = "fallback";
    agentic.fallback_reason = "orchestrator_no_final:budget:timeout";
    agentic.final = null;
    const model = passportModel({ run: done(payload) })!;
    expect(model.agents.mode).toBe("fallback");
    expect(rowOf(model.agents.rows, "mode").value).toContain("orchestrator_no_final:budget:timeout");
    expect(rowOf(model.agents.rows, "outcome").tone).toBe("warn");
  });

  it("отказ по плану и выключенные агенты различаются", () => {
    const refused = passportModel({ run: done(fixture("risk-reserve-off")) })!;
    expect(rowOf(refused.agents.rows, "outcome").value).toContain("отказал");
    const off = clone(baselineOld) as unknown as ScreenPayload;
    off.decision.agentic = null;
    off.agentic_state = { mode: "disabled", outcome: "skipped", reason: "agents_disabled", note: "" };
    expect(passportModel({ run: done(off) })!.agents.mode).toBe("disabled");
  });

  it("выбор не изменился — сказано прямо", () => {
    const model = passportModel({ run: done(fixture("normal")) })!;
    expect(rowOf(model.agents.rows, "outcome").value).toContain("выбор не изменился");
  });
});

describe("P3 — печать и незавершённый прогон", () => {
  it("печатает только паспорт и снимает флаг после печати", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {
      expect(document.documentElement.dataset.print).toBe("evidence-passport");
      window.dispatchEvent(new Event("afterprint"));
    });
    render(<EvidencePassport run={done(fixture("normal"))} research={research} />);
    fireEvent.click(screen.getByRole("button", { name: "Печать паспорта" }));
    expect(print).toHaveBeenCalledOnce();
    expect(document.documentElement.dataset.print).toBeUndefined();
    print.mockRestore();
  });

  it("во время прогона паспорт не строится", () => {
    const { container } = render(<EvidencePassport run={done(fixture("normal"), { status: "running" })} />);
    expect(container).toBeEmptyDOMElement();
  });
});
