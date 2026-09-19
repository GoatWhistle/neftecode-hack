import type { ScreenPayload, TankDefault } from "./types";
import { MISSING, isNumber, num } from "./format";

export type OriginKey = "given" | "derived" | "measured" | "scenario" | "open";

export interface OriginMeta {
  short: string;
  full: string;
}

const ORIGIN_META: Record<OriginKey, OriginMeta> = {
  given: { short: "выдано", full: "выдано организаторами в ТЗ или ответе эксперта" },
  derived: { short: "расчёт", full: "выведено из данных завода нашим расчётом" },
  measured: { short: "измерение", full: "измерение с установки на момент решения" },
  scenario: { short: "сценарий", full: "допущение сценария: не измерение и не требование ТЗ" },
  open: { short: "неизвестно", full: "величина не определена ни данными, ни требованием" }
};

export function isOriginKey(value: unknown): value is OriginKey {
  return typeof value === "string" && value in ORIGIN_META;
}

export function originMeta(value: string | null | undefined): OriginMeta | null {
  if (!isOriginKey(value)) return null;
  return ORIGIN_META[value];
}

export function originFull(value: string | null | undefined): string {
  const meta = originMeta(value);
  if (meta) return meta.full;
  return value ? value : MISSING;
}

export function tanksOf(payload: ScreenPayload): TankDefault[] {
  return payload.defaults?.tanks ?? [];
}

export function tankOf(payload: ScreenPayload, id: string): TankDefault | null {
  return tanksOf(payload).find((tank) => tank.id === id) ?? null;
}

export interface StockLine {
  text: string;
  onDemand: boolean;
  unavailable: boolean;
  origin: OriginKey;
  hint: string;
}

export function stockLine(payload: ScreenPayload, id: string): StockLine {
  const tank = tankOf(payload, id);
  const stock = payload.inventories?.[id];
  if (tank?.on_demand && tank.available === false) {
    return {
      text: "наработка остановлена",
      onDemand: true,
      unavailable: true,
      origin: "scenario",
      hint: "компонент нарабатывают под заявку, но его производство выключено условиями сценария: взять его неоткуда"
    };
  }
  if (tank?.on_demand) {
    return {
      text: "по необходимости",
      onDemand: true,
      unavailable: false,
      origin: "scenario",
      hint: "запаса на складе нет: компонент нарабатывают под заявку, ограничение — темп наработки"
    };
  }
  if (tank && tank.available === false) {
    return {
      text: isNumber(stock) ? `${num(stock, 1)} т, выведен` : "выведен из работы",
      onDemand: false,
      unavailable: true,
      origin: "scenario",
      hint: "компонент выведен из работы условиями сценария и в смешение не идёт"
    };
  }
  return {
    text: isNumber(stock) ? `${num(stock, 1)} т` : MISSING,
    onDemand: false,
    unavailable: false,
    origin: "scenario",
    hint: "начальный запас резервуара задан сценарием, не измерен"
  };
}

export function onDemandIds(payload: ScreenPayload): string[] {
  return tanksOf(payload)
    .filter((tank) => tank.on_demand)
    .map((tank) => tank.id);
}
