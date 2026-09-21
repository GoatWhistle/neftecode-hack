import { useEffect, useState } from "react";
import type { ScreenPayload } from "../types";
import type { RunState } from "../run/types";
import { EMPTY_RUN } from "../run/types";
import { AgentContribution } from "../agents/AgentContribution";
import { PlanCompare } from "../compare/PlanCompare";

const CASES = [
  { id: "risk_scripted", label: "sour_crude · scripted · opinions=2" },
  { id: "risk", label: "sour_crude · fallback llm_error:quota · opinions=0" },
  { id: "sour", label: "живой sour_crude · selected" },
  { id: "baddata", label: "живой baseline+both_broken · skipped" },
  { id: "nofeas", label: "живой no_feasible · confirmed_legacy" }
];

function runOf(payload: ScreenPayload | null): RunState {
  return { ...EMPTY_RUN, status: payload ? "done" : "idle", payload };
}

export function ContributionHarness() {
  const [id, setId] = useState(CASES[0]?.id ?? "risk_scripted");
  const [payload, setPayload] = useState<ScreenPayload | null>(null);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setPayload(null);
    setError(null);
    fetch(`./f0405/${id}.json`)
      .then((response) => response.json())
      .then((data: ScreenPayload) => {
        if (alive) setPayload(data);
      })
      .catch(() => {
        if (alive) setError("Фикстура не загрузилась");
      });
    return () => {
      alive = false;
    };
  }, [id]);

  const base = runOf(payload);
  const run: RunState = live
    ? { ...base, status: "running", agentEvents: [
        { seq: 1, agent: "orchestrator", step: 1, kind: "llm_call", elapsedMs: 800 },
        { seq: 2, agent: "orchestrator", step: 1, kind: "consult",
          tool_name: "ask_quality_agent", elapsedMs: 1200 },
        { seq: 3, agent: "quality", step: 1, kind: "tool",
          tool_name: "get_quality_margins", elapsedMs: 1600 }
      ] }
    : base;

  return (
    <main className="app">
      <div className="harness">
        <div className="harness__bar">
          {CASES.map((item) => (
            <button
              key={item.id}
              type="button"
              className="harness__tab"
              aria-pressed={id === item.id}
              onClick={() => setId(item.id)}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            className="harness__tab"
            aria-pressed={live}
            onClick={() => setLive((prev) => !prev)}
          >
            во время выполнения
          </button>
        </div>

        {error !== null ? <p>{error}</p> : null}

        <div className="harness__stack">
          <AgentContribution run={run} />
          {payload !== null ? <PlanCompare payload={payload} /> : null}
        </div>
      </div>
    </main>
  );
}
