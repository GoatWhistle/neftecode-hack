import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { GraphFacts } from "./GraphFacts";
import type { GraphModel, GraphNode } from "./model";

function node(overrides: Partial<GraphNode>): GraphNode {
  return {
    id: "quality",
    title: "Агент качества",
    kind: "specialist",
    role: "",
    x: 0,
    y: 0,
    bornAt: 0,
    calls: 1,
    tools: [],
    verdict: null,
    risk: null,
    confidence: null,
    confidenceCalibrated: null,
    valid: null,
    events: [],
    ...overrides
  };
}

const specialist = node({ id: "quality", verdict: null });

// Оркестратор спросил quality, ответа (edge kind="answer") нет — незавершённый диалог.
const unansweredModel: GraphModel = {
  nodes: [specialist],
  edges: [
    {
      id: "ask-1",
      from: "orchestrator",
      to: "quality",
      kind: "ask",
      tone: "neutral",
      label: "спросил",
      detail: null,
      order: 0,
      seq: 1,
      atMs: 0,
      spentMs: null,
      events: []
    }
  ],
  steps: 1,
  width: 100,
  height: 100,
  absent: null
};

describe("GraphFacts — отсутствие возражений не значит согласие всех (F4)", () => {
  it("не показывает «все согласились», когда специалист спрошен, но не ответил", () => {
    render(<GraphFacts model={unansweredModel} selected={null} reveal={1} />);
    expect(screen.queryByText(/согласились/)).toBeNull();
    expect(screen.getByText(/незавершённый диалог/)).toBeTruthy();
  });

  it("подписывает самооценку словом и не выдаёт число за калиброванную вероятность", () => {
    const withConfidence: GraphModel = {
      ...unansweredModel,
      nodes: [node({ confidence: 0.6, confidenceCalibrated: false })]
    };
    render(<GraphFacts model={withConfidence} selected="quality" reveal={1} />);
    expect(screen.getByText(/не калибрована/)).toBeTruthy();
  });
});
