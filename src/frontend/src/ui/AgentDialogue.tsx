import type { AgentEvent, StageFacts } from "../run/types";
import type { Agentic } from "../types";
import { buildActs } from "../run/agentActs";
import { moveOffsets } from "../run/orchSteps";
import { budgetRows, providerBand, spendRows, totalCalls } from "../run/agentMeters";
import { BudgetMeter, ProviderStrip, WaitingCounter } from "./AgentMeters";
import { ConsultCard } from "./ConsultCard";
import { ChoiceAgreement, FallbackPlate, GuardPlate, OverridePlate } from "./AgentBreak";
import { OrchMoves } from "./OrchMove";
import { AGENT_NAMES } from "../run/agentEvents";
import { Empty } from "./Primitives";

export interface AgentDialogueProps {
  events: AgentEvent[];
  running: boolean;
  facts: StageFacts | undefined;
  agentic: Agentic | null;
  elapsedMs: number;
  lastFrameAt: number | null;
}

export function AgentDialogue({ events, running, facts, agentic, elapsedMs, lastFrameAt }: AgentDialogueProps) {
  const band = providerBand(facts, agentic);
  const deterministic = band?.deterministic === true;
  const acts = buildActs(events);
  const offsets = moveOffsets(acts);
  const rows = budgetRows(events, facts, agentic?.budget);
  const total = totalCalls(events, agentic?.budget);
  const spend = spendRows(facts, agentic?.budget);
  const lastMs = events[events.length - 1]?.elapsedMs ?? 0;
  const overridden = agentic?.llm_choice_overridden;

  return (
    <div className="dialogue">
      <ProviderStrip band={band} label={agentic?.provider_label} />

      {events.length === 0 ? (
        <Empty>
          {running
            ? "Событий от агентов ещё не приходило."
            : "События агентов по этому прогону не передавались."}
        </Empty>
      ) : (
        <>
          <p className="dialogue__counter" role="status">
            Событий получено: {events.length}
            {running ? ", поток продолжается" : ", поток закрыт"}
          </p>
          <ol className="dialogue__acts">
            {acts.map((act, index) => {
              const actor = act.kind === "consult"
                ? act.role
                : act.kind === "orchestrator"
                  ? act.agent
                  : "system";
              const body = (() => {
                if (act.kind === "consult") {
                  const next = acts[index + 1];
                  const broke = next && next.kind === "fallback" ? next.event : null;
                  return <ConsultCard act={act} deterministic={deterministic} closed={!running}
                    facts={facts} breakEvent={broke} />;
                }
                if (act.kind === "guard") return <GuardPlate act={act} />;
                if (act.kind === "override") return <OverridePlate act={act} />;
                if (act.kind === "fallback") return <FallbackPlate act={act} />;
                if (act.kind === "orchestrator") {
                  return <OrchMoves act={act} deterministic={deterministic} facts={facts}
                    band={band} offset={offsets.get(act.key) ?? 0} />;
                }
                return null;
              })();
              if (body === null) return null;
              const previous = index === 0 ? null : acts[index - 1];
              const before = previous === undefined || previous === null
                ? null
                : previous.kind === "consult"
                  ? previous.role
                  : previous.kind === "orchestrator"
                    ? previous.agent
                    : "system";
              return (
                <li key={act.key}
                  className={`dialogue__act dialogue__act--${actor}${
                    running && index === acts.length - 1 ? " dialogue__act--live" : ""}`}>
                  <p className={`dialogue__actor${before === actor ? " dialogue__actor--same" : ""}`}>
                    <span className="dialogue__actor-mark" aria-hidden="true" />
                    <span className="dialogue__actor-name">{AGENT_NAMES[actor] ?? actor}</span>
                  </p>
                  {body}
                </li>
              );
            })}
          </ol>
        </>
      )}

      {running ? null : <ChoiceAgreement overridden={overridden} />}

      {running && !deterministic ? <WaitingCounter elapsedMs={elapsedMs} sinceMs={lastMs} lastFrameAt={lastFrameAt} /> : null}

      <BudgetMeter rows={rows} total={total} spend={spend} />
    </div>
  );
}
