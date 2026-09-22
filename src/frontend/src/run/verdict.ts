import type { NextStep, RiskItem, ScreenPayload } from "../types";

export type VerdictTone = "ok" | "warn" | "refuse" | "broken" | "stopped";

export interface VerdictLine {
  kind: string;
  text: string;
}

export interface Verdict {
  tone: VerdictTone;
  title: string;
  qualifier: string | null;
  backendStatus: string | null;
  backendLabel: string | null;
  lines: VerdictLine[];
}

export type RunOutcome =
  | { kind: "result"; payload: ScreenPayload }
  | { kind: "error"; message: string }
  | { kind: "stopped" };

const REFUSAL_REASON: Record<string, string> = {
  bad_data: "нет достоверного источника качества, поиск плана не проводился",
  model_not_applicable: "текущий режим вышел за объявленную область применимости модели",
  no_feasible_plan: "поиск планов прошёл, ни один не прошёл обязательные проверки",
  tank_phase_sensitive: "среди рассмотренных планов не подтверждён общий вариант для всех возможных фаз парка",
  agent_rejected: "допустимый план был, агенты качества или надёжности его отклонили"
};

const SERIOUS_RISK_KINDS = new Set([
  "fragile_plan",
  "tank_estimate_sensitive",
  "tank_phase_sensitive",
  "refused_on_tank_phase",
  "refused_on_data",
  "source_degraded",
  "sulfur_operating_margin"
]);

export function riskItemsOf(payload: ScreenPayload): RiskItem[] {
  return payload.explanation.risk?.items ?? [];
}

export function seriousRiskItems(payload: ScreenPayload): RiskItem[] {
  return riskItemsOf(payload).filter(
    (item) => item.level === "high" || item.level === "medium" || SERIOUS_RISK_KINDS.has(item.kind)
  );
}

const AT_HOUR = /^(.*?) на (\d+(?:[.,]\d+)?) ч$/;

function collapseSteps(steps: NextStep[]): NextStep[] {
  const order: string[] = [];
  const groups = new Map<string, { step: NextStep; hours: number[] }>();
  const plain: NextStep[] = [];
  for (const step of steps) {
    const match = AT_HOUR.exec(step.need);
    if (match === null) {
      plain.push(step);
      continue;
    }
    const head = match[1] ?? "";
    const hour = Number((match[2] ?? "").replace(",", "."));
    if (head === "" || !Number.isFinite(hour)) {
      plain.push(step);
      continue;
    }
    const found = groups.get(head);
    if (found === undefined) {
      order.push(head);
      groups.set(head, { step, hours: [hour] });
    } else {
      found.hours.push(hour);
    }
  }
  const merged = order.flatMap((head) => {
    const group = groups.get(head);
    if (group === undefined) return [];
    if (group.hours.length < 2) return [group.step];
    const first = Math.min(...group.hours);
    const last = Math.max(...group.hours);
    const span = hourWord(first) + " — " + hourWord(last);
    return [{ ...group.step, need: `${head} на всём интервале ${span} ч` }];
  });
  return [...merged, ...plain];
}

function hourWord(hour: number): string {
  return Number.isInteger(hour) ? String(hour) : String(hour).replace(".", ",");
}

function refusalLines(payload: ScreenPayload): VerdictLine[] {
  const lines: VerdictLine[] = [];
  const kind = payload.explanation.kind;
  const reason = kind ? REFUSAL_REASON[kind] : undefined;
  lines.push({
    kind: "cause",
    text: reason ? `Причина отказа: ${reason}.` : "Причина отказа: расчёт отказал, подробности ниже."
  });
  const steps = payload.explanation.next_steps ?? [];
  const seen = new Set<string>();
  for (const step of collapseSteps(steps)) {
    const wait =
      typeof step.available_in_hours === "number" && Number.isFinite(step.available_in_hours)
        ? ` (появится через ${step.available_in_hours} ч)`
        : "";
    const caveat = step.caveat ? ` ${step.caveat}` : "";
    const text = `Для повторного расчёта нужно: ${step.need}${wait}.${caveat}`;
    if (seen.has(text)) continue;
    seen.add(text);
    lines.push({ kind: "need", text });
  }
  if (steps.length === 0) {
    lines.push({
      kind: "need",
      text: "Что требуется для повторного расчёта, backend отдельным списком не передал."
    });
  }
  return lines;
}

function holdQualifier(payload: ScreenPayload): string | null {
  const serious = seriousRiskItems(payload);
  const warnings = payload.explanation.warnings ?? [];
  if (serious.length > 0 || warnings.length > 0) return "Есть ограничения";
  return null;
}

function planQualifier(payload: ScreenPayload): string | null {
  return seriousRiskItems(payload).length > 0 ? "Есть ограничения" : null;
}

function resultVerdict(payload: ScreenPayload): Verdict {
  const status = payload.decision.status;
  const backendLabel = payload.status_label ?? null;
  if (status === "refuse") {
    return {
      tone: "refuse",
      title: "Решение не выдано",
      qualifier: null,
      backendStatus: status,
      backendLabel,
      lines: refusalLines(payload)
    };
  }
  if (status === "hold") {
    const qualifier = holdQualifier(payload);
    return {
      tone: qualifier ? "warn" : "ok",
      title: "Сохранить режим",
      qualifier,
      backendStatus: status,
      backendLabel,
      lines: []
    };
  }
  if (status === "recommend_scenario") {
    const qualifier = planQualifier(payload);
    return {
      tone: qualifier ? "warn" : "ok",
      title: "Предложен сценарный план",
      qualifier,
      backendStatus: status,
      backendLabel,
      lines: []
    };
  }
  return {
    tone: "warn",
    title: backendLabel ?? "Статус решения не распознан",
    qualifier: null,
    backendStatus: status ?? null,
    backendLabel,
    lines: [{ kind: "cause", text: `Backend вернул статус «${status}», карты представления для него нет.` }]
  };
}

export function verdictOf(outcome: RunOutcome): Verdict {
  if (outcome.kind === "stopped") {
    return {
      tone: "stopped",
      title: "Показ остановлен",
      qualifier: null,
      backendStatus: null,
      backendLabel: null,
      lines: [
        { kind: "cause", text: "Показ прерван в браузере до получения решения; расчёт на сервере мог продолжиться." },
        {
          kind: "need",
          text: "Это не отказ по технологии и не успешное завершение: результата нет, запустите расчёт заново."
        }
      ]
    };
  }
  if (outcome.kind === "error") {
    return {
      tone: "broken",
      title: "Расчёт не завершён",
      qualifier: null,
      backendStatus: null,
      backendLabel: null,
      lines: [
        { kind: "cause", text: `Ошибка: ${outcome.message}.` },
        {
          kind: "need",
          text: "Это сбой связи или расчёта, а не технологический отказ. Повторите запуск."
        }
      ]
    };
  }
  return resultVerdict(outcome.payload);
}

export function outcomeOf(
  status: string,
  payload: ScreenPayload | null,
  error: string | null,
  stopped: boolean
): RunOutcome | null {
  if (stopped) return { kind: "stopped" };
  if (status === "failed") return { kind: "error", message: error ?? "причина не передана" };
  if (payload) return { kind: "result", payload };
  return null;
}
