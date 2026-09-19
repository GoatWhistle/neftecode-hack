import { num } from "../format";
import type { StageFacts } from "./types";

export interface FactLine {
  label: string;
  value: string;
  tone: "pass" | "fail" | "unknown" | "idle";
}

export interface FactSource {
  name: string;
  value: string;
  age: string;
  usable: boolean;
  status: string;
}

const NOT_SENT = "не передавалось";

function plural(count: number, one: string, few: string, many: string): string {
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return many;
  const last = count % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

export function inventoryLines(facts: StageFacts | undefined): FactLine[] {
  const stock = facts?.inventories;
  if (!stock) return [];
  return Object.entries(stock).map(([key, value]) => ({
    label: key,
    value: `${num(value, 1)} т`,
    tone: value > 0 ? "idle" : "unknown"
  }));
}

export function trustSources(facts: StageFacts | undefined): FactSource[] {
  const list = facts?.sources;
  if (!Array.isArray(list)) return [];
  return list.map((item) => {
    const age = item["age_hours"];
    const value = item["value"];
    return {
      name: String(item["name"] ?? "источник без имени"),
      value: typeof value === "number" ? `${num(value, 2)} мг/кг` : NOT_SENT,
      age: typeof age === "number" ? `${num(age, 1)} ч` : "возраст не передан",
      usable: item["usable"] === true,
      status: String(item["status"] ?? "")
    };
  });
}

export function forecastLines(facts: StageFacts | undefined): FactLine[] {
  if (!facts) return [];
  const out: FactLine[] = [];
  if (facts.available === false) {
    out.push({ label: "Расчёт за горизонтом", value: "не выполнялся", tone: "unknown" });
    return out;
  }
  if (typeof facts.lookahead_hours === "number") {
    out.push({ label: "Горизонт", value: `${num(facts.lookahead_hours, 0)} ч`, tone: "idle" });
  }
  if (typeof facts.min_reaction_hours === "number") {
    out.push({ label: "Запас реакции", value: `${num(facts.min_reaction_hours, 0)} ч`, tone: "idle" });
  }
  if (typeof facts.hours_to_violation === "number") {
    const window = typeof facts.min_reaction_hours === "number" ? facts.min_reaction_hours : null;
    out.push({
      label: "До нарушения",
      value: `${num(facts.hours_to_violation, 1)} ч`,
      tone: window !== null && facts.hours_to_violation < window ? "fail" : "pass"
    });
  } else if (facts.available === true) {
    out.push({ label: "До нарушения", value: "за горизонтом не наступает", tone: "pass" });
  }
  if (typeof facts.stock_ends_at_hours === "number") {
    out.push({ label: "Запас компонента кончится", value: `${num(facts.stock_ends_at_hours, 1)} ч`, tone: "unknown" });
  }
  if (facts.switched === true) {
    out.push({ label: "План", value: "заменён по упреждению", tone: "fail" });
  } else if (facts.switched === false) {
    out.push({ label: "План", value: "оставлен прежним", tone: "pass" });
  }
  return out;
}

export function candidateLines(facts: StageFacts | undefined): FactLine[] {
  if (!facts) return [];
  const out: FactLine[] = [];
  if (typeof facts.evaluated === "number") {
    out.push({ label: "Планов просчитано", value: String(facts.evaluated), tone: "idle" });
  }
  if (typeof facts.rounds === "number") {
    out.push({
      label: "Раундов отбора",
      value: `${facts.rounds} ${plural(facts.rounds, "раунд", "раунда", "раундов")}`,
      tone: "idle"
    });
  }
  if (typeof facts.feasible === "number") {
    out.push({
      label: "Прошли ограничения",
      value: String(facts.feasible),
      tone: facts.feasible > 0 ? "pass" : "fail"
    });
  }
  return out;
}

export function gateLines(facts: StageFacts | undefined): FactLine[] {
  if (!facts) return [];
  const out: FactLine[] = [];
  if (typeof facts.checks === "number") {
    out.push({
      label: "Проверок выполнено",
      value: `${facts.checks} ${plural(facts.checks, "проверка", "проверки", "проверок")}`,
      tone: "idle"
    });
  }
  if (typeof facts.feasible === "boolean") {
    out.push({
      label: "Выбранный план",
      value: facts.feasible ? "проверки пройдены" : "проверки не пройдены",
      tone: facts.feasible ? "pass" : "fail"
    });
  }
  if (typeof facts.plan_id === "string") {
    out.push({ label: "План", value: facts.plan_id, tone: "idle" });
  }
  return out;
}

export function choiceLines(facts: StageFacts | undefined): FactLine[] {
  if (!facts) return [];
  const out: FactLine[] = [];
  if (typeof facts.plan_id === "string") {
    out.push({ label: "Выбран план", value: facts.plan_id, tone: "idle" });
  }
  if (typeof facts.alternatives === "number") {
    out.push({
      label: "Альтернатив рядом",
      value: String(facts.alternatives),
      tone: "idle"
    });
  }
  return out;
}

export function trustVerdict(facts: StageFacts | undefined): FactLine[] {
  if (!facts) return [];
  const out: FactLine[] = [];
  if (typeof facts.usable === "boolean") {
    out.push({
      label: "Пригодный источник",
      value: facts.usable ? "найден" : "не найден",
      tone: facts.usable ? "pass" : "fail"
    });
  }
  if (typeof facts.primary === "string") {
    out.push({ label: "Основной источник", value: facts.primary, tone: "idle" });
  }
  return out;
}
