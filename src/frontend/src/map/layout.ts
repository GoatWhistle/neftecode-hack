import { useEffect, useState } from "react";
import { INPUT_SCENARIO, TERMINAL_HOLD, TERMINAL_RECOMMEND, TERMINAL_REFUSE } from "./graph";

export type RowDirection = "ltr" | "rtl";

export type MapColumns = 4 | 2 | 1;

export interface MapRow {
  key: string;
  contour: string;
  direction: RowDirection;
  cells: string[];
  terminals?: string[];
}

const ROWS_4: readonly MapRow[] = [
  {
    key: "row-data",
    contour: "Контур данных",
    direction: "ltr",
    cells: [INPUT_SCENARIO, "state", "trust", "candidates"]
  },
  {
    key: "row-decision",
    contour: "Контур решения",
    direction: "rtl",
    cells: ["forecast", "choice", "gate"]
  },
  {
    key: "row-agents",
    contour: "Слой агентов",
    direction: "ltr",
    cells: ["agents", "decision"],
    terminals: [TERMINAL_HOLD, TERMINAL_RECOMMEND, TERMINAL_REFUSE]
  }
];

const ROWS_2: readonly MapRow[] = [
  {
    key: "row-1",
    contour: "Контур данных",
    direction: "ltr",
    cells: [INPUT_SCENARIO, "state"]
  },
  {
    key: "row-2",
    contour: "Контур данных",
    direction: "rtl",
    cells: ["trust", "candidates"]
  },
  {
    key: "row-3",
    contour: "Контур решения",
    direction: "ltr",
    cells: ["forecast", "choice"]
  },
  {
    key: "row-4",
    contour: "Контур решения",
    direction: "rtl",
    cells: ["gate", "agents"]
  },
  {
    key: "row-5",
    contour: "Слой агентов",
    direction: "ltr",
    cells: ["decision"],
    terminals: [TERMINAL_HOLD, TERMINAL_RECOMMEND, TERMINAL_REFUSE]
  }
];

const ROWS_1: readonly MapRow[] = [
  { key: "row-in", contour: "Контур данных", direction: "ltr", cells: [INPUT_SCENARIO] },
  { key: "row-state", contour: "Контур данных", direction: "ltr", cells: ["state"] },
  { key: "row-trust", contour: "Контур данных", direction: "ltr", cells: ["trust"] },
  { key: "row-candidates", contour: "Контур данных", direction: "ltr", cells: ["candidates"] },
  { key: "row-forecast", contour: "Контур решения", direction: "ltr", cells: ["forecast"] },
  { key: "row-choice", contour: "Контур решения", direction: "ltr", cells: ["choice"] },
  { key: "row-gate", contour: "Контур решения", direction: "ltr", cells: ["gate"] },
  { key: "row-agents-1", contour: "Слой агентов", direction: "ltr", cells: ["agents"] },
  {
    key: "row-decision-1",
    contour: "Слой агентов",
    direction: "ltr",
    cells: ["decision"],
    terminals: [TERMINAL_HOLD, TERMINAL_RECOMMEND, TERMINAL_REFUSE]
  }
];

const ROWS_BY_COLUMNS: Record<MapColumns, readonly MapRow[]> = {
  4: ROWS_4,
  2: ROWS_2,
  1: ROWS_1
};

const QUERY_UNDER_1100 = "(max-width: 1100px)";
const QUERY_UNDER_720 = "(max-width: 720px)";

function readColumns(): MapColumns {
  if (typeof window === "undefined") return 4;
  if (window.matchMedia(QUERY_UNDER_720).matches) return 1;
  if (window.matchMedia(QUERY_UNDER_1100).matches) return 2;
  return 4;
}

export function useMapColumns(): MapColumns {
  const [columns, setColumns] = useState<MapColumns>(readColumns);

  useEffect(() => {
    const wide = window.matchMedia(QUERY_UNDER_1100);
    const narrow = window.matchMedia(QUERY_UNDER_720);
    const onChange = () => setColumns(readColumns());
    wide.addEventListener("change", onChange);
    narrow.addEventListener("change", onChange);
    onChange();
    return () => {
      wide.removeEventListener("change", onChange);
      narrow.removeEventListener("change", onChange);
    };
  }, []);

  return columns;
}

export function mapRows(columns: MapColumns = 4): readonly MapRow[] {
  return ROWS_BY_COLUMNS[columns];
}

export function rowOf(id: string, columns: MapColumns = 4): MapRow | undefined {
  const rows = ROWS_BY_COLUMNS[columns];
  return rows.find((row) => row.cells.includes(id) || (row.terminals ?? []).includes(id));
}

export function directionOf(id: string, columns: MapColumns = 4): RowDirection {
  return rowOf(id, columns)?.direction ?? "ltr";
}
