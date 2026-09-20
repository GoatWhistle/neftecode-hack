export type NodeKind = "stage" | "input" | "terminal";

export type EdgeKind = "flow" | "loop" | "back" | "exit";

export interface MapNode {
  id: string;
  kind: NodeKind;
  label: string;
  order: number | null;
  artifact: string;
  waiting: string;
  /** Исходный код backend (decision.status и т.п.) для узлов, где label — человеческий перевод.
   *  Показывается мелко, рядом, а не вместо перевода — независимая проверка нашла, что терминальные
   *  узлы схемы показывали код (hold/recommend_scenario/refuse) как основной заголовок. */
  code?: string;
}

export interface MapEdge {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  label?: string;
}

export const INPUT_SCENARIO = "in-scenario";

export const TERMINAL_HOLD = "out-hold";
export const TERMINAL_RECOMMEND = "out-recommend";
export const TERMINAL_REFUSE = "out-refuse";

export const MAP_NODES: readonly MapNode[] = [
  {
    id: INPUT_SCENARIO,
    kind: "input",
    label: "Сценарий и срез",
    artifact: "условия прогона",
    waiting: "что задано до пуска",
    order: null
  },
  {
    id: "state",
    kind: "stage",
    label: "Состояние",
    artifact: "срез телеметрии",
    waiting: "снимет уставки, рецепт и запасы",
    order: 1
  },
  {
    id: "trust",
    kind: "stage",
    label: "Доверие к данным",
    artifact: "вердикт по источникам",
    waiting: "сверит возраст замеров с пределом",
    order: 2
  },
  {
    id: "candidates",
    kind: "stage",
    label: "Кандидаты",
    artifact: "optimizer · раунды поиска",
    waiting: "переберёт планы и отсеет недопустимые",
    order: 3
  },
  {
    id: "forecast",
    kind: "stage",
    label: "Прогноз",
    artifact: "траектория · упреждение",
    waiting: "посчитает ход свойств вперёд",
    order: 4
  },
  {
    id: "choice",
    kind: "stage",
    label: "Выбор",
    artifact: "выбранный план",
    waiting: "сравнит альтернативы и устойчивость",
    order: 5
  },
  {
    id: "gate",
    kind: "stage",
    label: "Gate",
    artifact: "жёсткие проверки",
    waiting: "проверит план по всем ограничениям",
    order: 6
  },
  {
    id: "agents",
    kind: "stage",
    label: "Агенты",
    artifact: "диалог · инструменты · вето",
    waiting: "агенты сузят выбор или наложат вето",
    order: 7
  },
  {
    id: "decision",
    kind: "stage",
    label: "Решение",
    artifact: "итог прогона",
    waiting: "соберёт вердикт и объяснение",
    order: 8
  },
  {
    id: TERMINAL_HOLD,
    kind: "terminal",
    label: "Сохранить режим",
    code: "hold",
    artifact: "держать режим",
    waiting: "исход: держать режим",
    order: null
  },
  {
    id: TERMINAL_RECOMMEND,
    kind: "terminal",
    label: "Изменить режим",
    code: "recommend_scenario",
    artifact: "предложить план",
    waiting: "исход: предложить план",
    order: null
  },
  {
    id: TERMINAL_REFUSE,
    kind: "terminal",
    label: "Отказ",
    code: "refuse",
    artifact: "отказ с причиной",
    waiting: "исход: отказ с причиной",
    order: null
  }
];

export const MAP_EDGES: readonly MapEdge[] = [
  { id: "e-in-state", from: INPUT_SCENARIO, to: "state", kind: "flow" },
  { id: "e-state-trust", from: "state", to: "trust", kind: "flow" },
  { id: "e-trust-candidates", from: "trust", to: "candidates", kind: "flow" },
  { id: "e-candidates-forecast", from: "candidates", to: "forecast", kind: "flow" },
  { id: "e-forecast-choice", from: "forecast", to: "choice", kind: "flow" },
  { id: "e-choice-gate", from: "choice", to: "gate", kind: "flow" },
  { id: "e-gate-agents", from: "gate", to: "agents", kind: "flow" },
  { id: "e-agents-decision", from: "agents", to: "decision", kind: "flow" },
  { id: "e-decision-hold", from: "decision", to: TERMINAL_HOLD, kind: "flow" },
  { id: "e-decision-recommend", from: "decision", to: TERMINAL_RECOMMEND, kind: "flow" },
  {
    id: "e-candidates-loop",
    from: "candidates",
    to: "candidates",
    kind: "loop",
    label: "вето сужает поиск"
  },
  { id: "e-agents-gate", from: "agents", to: "gate", kind: "back", label: "снова Gate" },
  { id: "x-trust", from: "trust", to: TERMINAL_REFUSE, kind: "exit", label: "отказ" },
  { id: "x-candidates", from: "candidates", to: TERMINAL_REFUSE, kind: "exit", label: "отказ" },
  { id: "x-gate", from: "gate", to: TERMINAL_REFUSE, kind: "exit", label: "отказ" },
  { id: "x-agents", from: "agents", to: TERMINAL_REFUSE, kind: "exit", label: "отказ" }
];

export const STAGE_NODES = MAP_NODES.filter((node) => node.kind === "stage");

export function nodeById(id: string): MapNode | undefined {
  return MAP_NODES.find((node) => node.id === id);
}
