import type { ScreenPayload } from "../types";

export type CheckTone = "pass" | "fail" | "warn" | "unknown";

export interface CheckFamily {
  id: string;
  title: string;
  tone: CheckTone;
  value: string;
  detail: string;
}

function nominal(payload: ScreenPayload): CheckFamily {
  const gate = payload.decision.gate;
  const checks = gate?.checks ?? [];
  if (!gate || checks.length === 0) {
    return {
      id: "nominal",
      title: "Номинальные проверки",
      tone: "unknown",
      value: "нет оценки",
      detail: "Протокол жёстких проверок не составлялся: расчёт до него не дошёл."
    };
  }
  const unknown = gate.unknown_requirements ?? [];
  if (!gate.feasible) {
    const first = gate.first_violation;
    return {
      id: "nominal",
      title: "Номинальные проверки",
      tone: "fail",
      value: "не пройдены",
      detail: first
        ? `Первое нарушение: ${first.constraint_id}.`
        : `Проверок в протоколе: ${checks.length}.`
    };
  }
  return {
    id: "nominal",
    title: "Номинальные проверки",
    tone: unknown.length > 0 ? "warn" : "pass",
    value: unknown.length > 0 ? "пройдены не полностью" : "пройдены",
    detail:
      unknown.length > 0
        ? `Проверок в протоколе: ${checks.length}; без оценки осталось требований: ${unknown.length}.`
        : `Проверок в протоколе: ${checks.length}, на номинальных значениях нарушений нет. Это не стресс-проверки.`
  };
}

function robustness(payload: ScreenPayload): CheckFamily {
  const robust = payload.decision.robustness;
  if (!robust) {
    return {
      id: "robustness",
      title: "Устойчивость к отклонениям",
      tone: "unknown",
      value: "нет оценки",
      detail: "Возмущения не прогонялись: плана, который можно было бы проверить, нет."
    };
  }
  const failedNames = robust.mandatory_failure_names ?? [];
  const declared = robust.perturbations_declared;
  const evaluated = robust.perturbations_evaluated;
  const notApplicable = robust.not_applicable;
  const base =
    `Проверено отклонений: ${evaluated} из ${declared} заявленных, ` +
    `неприменимо ${notApplicable}; выдержало ${robust.held}, нарушило ${robust.violated}. ` +
    "Это перечень посчитанных отклонений, а не вероятность безопасности.";
  if (robust.fragile) {
    return {
      id: "robustness",
      title: "Устойчивость к отклонениям",
      tone: "fail",
      value: "план хрупкий",
      detail: failedNames.length > 0 ? `${base} Обязательные не выдержали: ${failedNames.join(", ")}.` : base
    };
  }
  if (robust.violated > 0) {
    return {
      id: "robustness",
      title: "Устойчивость к отклонениям",
      tone: "warn",
      value: "выдержал не все",
      detail: base
    };
  }
  return {
    id: "robustness",
    title: "Устойчивость к отклонениям",
    tone: evaluated > 0 ? "pass" : "unknown",
    value: evaluated > 0 ? "выдержал проверенные" : "нет оценки",
    detail: base
  };
}

function readiness(payload: ScreenPayload): CheckFamily {
  const deployment = payload.decision.deployment_readiness;
  const scope = payload.decision.scope;
  const scopeText =
    scope === "synthetic_scenario"
      ? " Это модельный результат, а не измеренный эффект на заводе; происхождение каждого входа (измерение или сценарная уставка) указано отдельно в источниках."
      : "";
  if (!deployment) {
    return {
      id: "readiness",
      title: "Данные и допущения",
      tone: "unknown",
      value: "нет оценки",
      detail: `Готовность к применению backend не передавал.${scopeText}`
    };
  }
  const open = (deployment.required_inputs ?? []).filter((item) => item.status === "open");
  if (deployment.ready) {
    return {
      id: "readiness",
      title: "Данные и допущения",
      tone: "pass",
      value: "вводные получены",
      detail: `${deployment.reason}${scopeText}`
    };
  }
  const missing = open.map((item) => item.label).join("; ");
  return {
    id: "readiness",
    title: "Данные и допущения",
    tone: "warn",
    value: "прототип, промышленное применение закрыто",
    detail:
      `${deployment.reason}${missing ? ` Не передано: ${missing}.` : ""}` +
      ` Это граница области применения прототипа, а не причина конкретного решения.${scopeText}`
  };
}

export function checkFamilies(payload: ScreenPayload): CheckFamily[] {
  return [nominal(payload), robustness(payload), readiness(payload)];
}
