export type PresetKey = "normal" | "risk" | "bad-data";

export interface Preset {
  label: string;
  title: string;
  note: string;
  scenario: string;
  snapshot: string;
  fault: string;
}

export const PRESETS: Record<PresetKey, Preset> = {
  normal: {
    label: "Норма",
    title: "Не вмешиваться без причины",
    note: "Устойчивый период: система должна обосновать сохранение режима.",
    scenario: "baseline",
    snapshot: "20260105-080000",
    fault: "healthy"
  },
  risk: {
    label: "Риск качества",
    title: "Найти допустимый компромисс",
    note: "Сернистое сырьё, задержка отклика и ограниченный резерв компонента.",
    scenario: "sour_crude",
    snapshot: "20260724-030000",
    fault: "healthy"
  },
  "bad-data": {
    label: "Плохие данные",
    title: "Отказаться от рискованного совета",
    note: "Лаборатория и поточный анализатор недоступны одновременно.",
    scenario: "baseline",
    snapshot: "20260416-101000",
    fault: "both_broken"
  }
};

export const PRESET_ORDER: PresetKey[] = ["normal", "risk", "bad-data"];

export interface PresetMatch {
  scenario: string;
  snapshot: string;
  fault: string;
}

export function presetOf(conditions: PresetMatch): PresetKey | null {
  return PRESET_ORDER.find((key) => {
    const p = PRESETS[key];
    return p.scenario === conditions.scenario && p.snapshot === conditions.snapshot && p.fault === conditions.fault;
  }) ?? null;
}
