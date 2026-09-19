import type { AgentEvent, StageFacts } from "../run/types";
import type { Agentic } from "../types";
import { buildActs } from "../run/agentActs";
import { budgetRows, providerBand, spendRows, totalCalls } from "../run/agentMeters";
import { BudgetMeter, ProviderStrip, WaitingCounter } from "./AgentMeters";
import { ConsultCard } from "./ConsultCard";
import { ActRow, ChoiceAgreement, FallbackPlate, GuardPlate, OverridePlate } from "./AgentBreak";
import { Empty } from "./Primitives";

export interface AgentDialogueProps {
  events: AgentEvent[];
  running: boolean;
  facts: StageFacts | undefined;
  agentic: Agentic | null;
  elapsedMs: number;
}

export function AgentDialogue({ events, running, facts, agentic, elapsedMs }: AgentDialogueProps) {
  const band = providerBand(facts, agentic);
  const deterministic = band?.deterministic === true;
  const acts = buildActs(events);
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
          <div className="dialogue__acts">
            {acts.map((act, index) => {
              if (act.kind === "consult") {
                const next = acts[index + 1];
                const broke = next && next.kind === "fallback" ? next.event : null;
                return (
                  <ConsultCard key={act.key} act={act} deterministic={deterministic} closed={!running}
                    facts={facts} breakEvent={broke} />
                );
              }
              if (act.kind === "guard") return <GuardPlate key={act.key} act={act} />;
              if (act.kind === "override") return <OverridePlate key={act.key} act={act} />;
              if (act.kind === "fallback") return <FallbackPlate key={act.key} act={act} />;
              if (act.kind === "orchestrator") {
                return <ActRow key={act.key} act={act} deterministic={deterministic} />;
              }
              return null;
            })}
          </div>
        </>
      )}

      {running ? null : <ChoiceAgreement overridden={overridden} />}

      {running && !deterministic ? <WaitingCounter elapsedMs={elapsedMs} sinceMs={lastMs} /> : null}

      <BudgetMeter rows={rows} total={total} spend={spend} />
    </div>
  );
}
