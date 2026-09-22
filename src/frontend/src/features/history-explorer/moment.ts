import type { HistoryCatalog, HistoryItem } from "./types";

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
  "сентября", "октября", "ноября", "декабря"];
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

interface Parts { year: string; month: number; day: string; hh: string; mm: string; ss: string }

/** Местное время источника разбирается как текст: без Date и без сдвига часового пояса. */
function parts(value: string): Parts | null {
  const iso = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(value);
  const key = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(value);
  const m = iso ?? key;
  if (!m) return null;
  return { year: m[1]!, month: Number(m[2]) - 1, day: m[3]!, hh: m[4] ?? "00", mm: m[5] ?? "00", ss: m[6] ?? "00" };
}

function clock(p: Parts): string {
  return p.ss === "00" ? `${p.hh}:${p.mm}` : `${p.hh}:${p.mm}:${p.ss}`;
}

/** «05 января 2026 · 08:00»; секунды показываются, только если они заданы. */
export function longMoment(value: string): string {
  const p = parts(value);
  return p ? `${p.day} ${MONTHS[p.month]} ${p.year} · ${clock(p)}` : value;
}

/** «05 янв · 08:00» для строки списка; год нужен, если эпизоды охватывают несколько лет. */
export function shortMoment(value: string, withYear = false): string {
  const p = parts(value);
  return p ? `${p.day} ${MONTHS_SHORT[p.month]}${withYear ? ` ${p.year}` : ""} · ${clock(p)}` : value;
}

export function localTime(value: string): string {
  return value.replace("T", " ");
}

/** Выбранный момент следующего запуска, собранный из условий формы. */
export interface MomentView {
  key: string;
  at: string;
  kind: "snapshot" | "synthetic" | "moment" | "scenario";
  label: string | null;
}

export const KIND_LABEL: Record<MomentView["kind"], string> = {
  snapshot: "Исторический срез",
  synthetic: "С искусственными изменениями",
  scenario: "Не измерения завода",
  moment: "Точный момент"
};

export function kindOf(item: HistoryItem): MomentView["kind"] {
  return item.synthetic_edits.length > 0 ? "synthetic" : "snapshot";
}

export function momentOf(
  form: { snapshot: string; at?: string },
  catalog: HistoryCatalog | null,
  titles: { key: string; title: string }[]
): MomentView | null {
  if (form.at) return { key: `at:${form.at}`, at: form.at, kind: "moment", label: null };
  if (!form.snapshot) return null;
  if (form.snapshot === "synthetic") return { key: "synthetic", at: "", kind: "scenario", label: null };
  const item = catalog?.items.find((entry) => entry.snapshot === form.snapshot);
  if (item) return { key: form.snapshot, at: item.at, kind: kindOf(item), label: item.label };
  const title = titles.find((entry) => entry.key === form.snapshot)?.title ?? null;
  return { key: form.snapshot, at: form.snapshot, kind: "snapshot", label: title };
}

/** Ключ момента для сравнения «условия следующего запуска» и «дата показанного ответа». */
export function momentKey(form: { snapshot: string; at?: string }): string {
  return form.at ? `at:${form.at}` : form.snapshot;
}
