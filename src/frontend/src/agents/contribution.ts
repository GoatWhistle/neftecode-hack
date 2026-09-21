import type { Agentic } from "../types";
import { CONSTRAINT_TEXT } from "../run/agentVocab";
import type { AgentEvent, RunState } from "../run/types";
import type { AgentCardModel, CardKey, CardTone, ContributionModel } from "./vocab";
import {
  OUTCOME_TEXT, RISK_TEXT, ROLE_TITLE, VERDICT_TEXT,
  absentText, constraintDetail, constraintLines, planChanged, skippedText, toolText
} from "./vocab";

export type { AgentCardModel, CardKey, CardTone, ConstraintLine, ContributionModel, EvidenceLine } from "./vocab";

function orchestratorCard(agentic: Agentic, events: AgentEvent[], running: boolean): AgentCardModel {
  const outcome = agentic.outcome;
  const applied = agentic.constraints_applied ?? [];
  const vetoed = Object.keys(agentic.vetoed_candidates ?? {});
  const trace = Array.isArray(agentic.trace) ? agentic.trace : [];
  const tools = trace
    .filter((item) => item && typeof item === "object" && (item as Record<string, unknown>)["kind"] === "tool")
    .map((item) => toolText((item as Record<string, unknown>)["tool_name"] as string | undefined))
    .filter((text): text is string => text !== null);
  const unique = [...new Set(tools)];
  const calls = agentic.budget?.llm_calls_by_role?.["orchestrator"];

  const checked = unique.length > 0
    ? `Запросил: ${unique.join(", ")}.`
    : typeof calls === "number" && calls > 0
      ? `До остановки успел обратиться к модели ${calls} раз, но ни один инструмент не отработал: результатов в трассе нет.`
      : "Инструментов в трассе этого прогона нет.";

  let concluded: string;
  let effect: string;
  let tone: CardTone = "done";

  if (running) {
    tone = "live";
    const last = events[events.length - 1];
    const call = last ? toolText(last.tool_name) ?? last.kind : null;
    concluded = call !== null ? `Последний подтверждённый шаг: ${call}.` : "Выводов ещё нет: прогон идёт.";
    effect = "Итог ещё не зафиксирован.";
  } else if (outcome === "fallback") {
    tone = "broken";
    const reason = agentic.fallback_reason ?? "причина не передана";
    concluded = `Финального ответа оркестратор не дал. Отметка сбоя: ${reason}.`;
    effect = applied.length > 0 || vetoed.length > 0
      ? `Выполненная часть сохранена: подтверждённых ограничений ${applied.length}, запретов на кандидатов ${vetoed.length}. Они остались в силе, откат к исходному плану поверх них не делался.`
      : "До сбоя ни одно ограничение и ни один запрет подтвердить не успели, поэтому решение осталось тем, что дал детерминированный расчёт.";
  } else if (outcome === "confirmed_legacy") {
    tone = "neutral";
    concluded = "Подтвердили исходный выбор детерминированного расчёта.";
    effect = "План не менялся: улучшения и запреты в этом прогоне не заявлены.";
  } else if (outcome === "refused") {
    tone = "neutral";
    concluded = "Свёл мнения и отказался выдавать рекомендацию.";
    effect = vetoed.length > 0
      ? `Запрет получили кандидаты: ${vetoed.join(", ")}.`
      : "Отказ не сопровождался запретом на конкретных кандидатов.";
  } else if (outcome === "selected") {
    const final = agentic.final;
    concluded = final
      ? `${final.summary}${final.candidate_id ? ` (${final.candidate_id})` : ""}.`
      : "Выбор зафиксирован, но текст итога не передан.";
    effect = planChanged(agentic)
      ? `Выбор шёл в изменённых границах: подтверждённых ограничений ${applied.length}, запретов ${vetoed.length}, повторный поиск в трассе есть.`
      : "Изменение плана относительно исходного расчёта из трассы не подтверждается: исходного и финального выбора рядом в ней нет.";
  } else {
    tone = "skipped";
    concluded = `Итог прогона: ${outcome}.`;
    effect = "Влияние на выбор по этому результату не установлено.";
  }

  const budget = agentic.budget;
  const tech: string[] = [];
  if (typeof budget?.llm_calls === "number") {
    tech.push(`обращений к модели ${budget.llm_calls}${typeof budget.max_llm_calls === "number" ? ` из ${budget.max_llm_calls}` : ""}`);
  }
  if (typeof budget?.replans === "number") tech.push(`повторных поисков ${budget.replans}`);
  const total = budget?.usage?.["total_tokens"];
  if (typeof total === "number" && total > 0) tech.push(`токенов ${total.toLocaleString("ru-RU")}`);

  return {
    key: "orchestrator",
    title: ROLE_TITLE.orchestrator,
    tone,
    state: running ? "идёт" : OUTCOME_TEXT[outcome] ?? outcome,
    checked,
    concluded,
    effect,
    invalid: false,
    constraints: applied.map((item, index) => ({
      key: `applied-${index}`,
      label: CONSTRAINT_TEXT[item.type] ?? item.type,
      detail: constraintDetail(item),
      applied: true
    })),
    evidence: (agentic.final?.evidence_refs ?? []).map((ref, index) => ({ key: `${ref}-${index}`, text: ref })),
    tech
  };
}

function specialistCard(key: CardKey, agentic: Agentic, events: AgentEvent[],
  running: boolean): AgentCardModel {
  const opinion = running
    ? null
    : (agentic.opinions ?? []).find((item) => item.role === key) ?? null;
  const applied = agentic.constraints_applied ?? [];
  const trace = Array.isArray(agentic.trace) ? agentic.trace : [];
  const tools = trace
    .filter((item) => {
      if (!item || typeof item !== "object") return false;
      const row = item as Record<string, unknown>;
      return row["agent"] === key && row["kind"] === "tool";
    })
    .map((item) => toolText((item as Record<string, unknown>)["tool_name"] as string | undefined))
    .filter((text): text is string => text !== null);
  const unique = [...new Set(tools)];

  if (opinion === null) {
    const mine = events.filter((event) => event.agent === key);
    const live = running ? mine.length : 0;
    const last = mine[mine.length - 1];
    return {
      key,
      title: ROLE_TITLE[key],
      tone: running && live > 0 ? "live" : "skipped",
      state: running ? (live > 0 ? "идёт" : "ждёт") : "мнения нет",
      checked: running
        ? (last ? `Последний подтверждённый шаг: ${toolText(last.tool_name) ?? last.kind}.` : "Обращений к этой роли ещё не было.")
        : unique.length > 0
          ? `Успел запросить: ${unique.join(", ")}.`
          : "К этой роли не обращались: инструментов и вызовов в трассе нет.",
      concluded: running
        ? "Мнение ещё не подано."
        : "Мнение в этом прогоне не подано, поэтому вывода у роли нет.",
      effect: running ? "Итог ещё не зафиксирован." : "На выбор плана эта роль здесь не повлияла.",
      invalid: false,
      constraints: [],
      evidence: [],
      tech: live > 0 ? [`событий ${live}`] : []
    };
  }

  const verdict = VERDICT_TEXT[opinion.verdict] ?? opinion.verdict;
  const risk = opinion.risk_level ? RISK_TEXT[opinion.risk_level] ?? opinion.risk_level : null;
  const lines = constraintLines(opinion, applied);
  const acceptedCount = lines.filter((line) => line.applied).length;

  let effect: string;
  if (!opinion.valid) {
    effect = "Мнение признано невалидным и в выбор не принято: его ограничения и вердикт не применялись.";
  } else if (lines.length === 0) {
    effect = "Ограничений не предлагала, поэтому границы выбора эта роль не меняла.";
  } else if (acceptedCount === 0) {
    effect = `Предложила ограничений: ${lines.length}. Ни одно не вошло в подтверждённые — границы выбора не изменились.`;
  } else {
    effect = `Предложила ограничений: ${lines.length}, подтверждено ${acceptedCount}. Подтверждённые действовали при выборе.`;
  }

  const tech: string[] = [];
  const consults = agentic.budget?.consults?.[key];
  if (typeof consults === "number") tech.push(`консультаций ${consults}`);
  const calls = agentic.budget?.llm_calls_by_role?.[key];
  if (typeof calls === "number") tech.push(`обращений к модели ${calls}`);

  return {
    key,
    title: ROLE_TITLE[key],
    tone: opinion.valid ? "done" : "broken",
    state: opinion.valid ? verdict : "мнение невалидно",
    checked: unique.length > 0 ? `Запросила: ${unique.join(", ")}.` : "Инструментов в трассе нет.",
    concluded: [
      `Вердикт: ${verdict}`,
      risk !== null ? `риск ${risk}` : null,
      typeof opinion.confidence === "number"
        ? `самооценка модели ${opinion.confidence.toFixed(2)} (не калибрована)`
        : null
    ].filter(Boolean).join(", ") + ".",
    effect,
    invalid: !opinion.valid,
    constraints: lines,
    evidence: opinion.reasons.map((reason, index) => ({
      key: `${reason.code}-${index}`,
      text: reason.candidate_id ? `${reason.text} (${reason.candidate_id})` : reason.text
    })),
    tech
  };
}

export function contributionModel(run: RunState): ContributionModel {
  const payload = run.payload;
  const agentic = payload?.decision.agentic ?? null;
  const running = run.status === "running";

  if (agentic === null) {
    if (running) {
      const seen = run.agentEvents;
      return {
        cards: (["orchestrator", "quality", "reliability"] as CardKey[]).map((key) => {
          const mine = seen.filter((event) => event.agent === key);
          const last = mine[mine.length - 1];
          return {
            key,
            title: ROLE_TITLE[key],
            tone: mine.length > 0 ? "live" : "idle",
            state: mine.length > 0 ? "идёт" : "ждёт",
            checked: last ? `Последний подтверждённый шаг: ${toolText(last.tool_name) ?? last.kind}.` : "Обращений ещё не было.",
            concluded: "Выводов ещё нет: прогон идёт.",
            effect: "Итог ещё не зафиксирован.",
            invalid: false,
            constraints: [],
            evidence: [],
            tech: mine.length > 0 ? [`событий ${mine.length}`] : []
          };
        }),
        headline: "Прогон идёт: показан последний подтверждённый обмен, а не итог.",
        running: true,
        absent: null
      };
    }
    return {
      cards: [], headline: "", running: false,
      absent: payload === null ? "Результата ещё нет." : absentText(payload)
    };
  }

  const skipped = skippedText(payload, agentic);
  if (skipped !== null && !running) {
    return { cards: [], headline: "", running: false, absent: skipped };
  }

  const cards: AgentCardModel[] = [
    orchestratorCard(agentic, run.agentEvents.filter((e) => e.agent === "orchestrator"), running),
    specialistCard("quality", agentic, run.agentEvents, running),
    specialistCard("reliability", agentic, run.agentEvents, running)
  ];

  const valid = (agentic.opinions ?? []).filter((item) => item.valid).length;
  const applied = (agentic.constraints_applied ?? []).length;
  const headline = running
    ? "Прогон идёт: показан последний подтверждённый обмен, а не итог."
    : `Валидных мнений ${valid}, подтверждённых ограничений ${applied}.`;

  return { cards, headline, running, absent: null };
}
