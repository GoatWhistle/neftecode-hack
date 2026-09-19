import type { ScreenPayload } from "../types";
import { STAGES } from "../stages";
import type { RunState } from "../run/types";
import { stageStateOf } from "../run/types";
import { agentCounters, keyNumbers, sourceLines } from "../run/summary";
import { RailGroup, RailLines } from "./RailGroup";
import { LampDot } from "./Primitives";

const STATE_MARK: Record<string, string> = {
  pending: "·",
  running: "→",
  done: "✓",
  failed: "×"
};

export interface RailProps {
  payload: ScreenPayload | null;
  active: string;
  run: RunState;
}

export function Rail({ payload, active, run }: RailProps) {
  const numbers = keyNumbers(payload);
  const sources = sourceLines(payload);
  const agents = agentCounters(payload);

  return (
    <aside className="rail" aria-label="Ход прогона">
      <RailGroup title="Этапы">
        <ol className="rail__list">
          <li className={`rail__item ${active === "config" ? "rail__item--active" : ""}`}>
            <a className="rail__link" href="#config">
              <span className="rail__order">0</span>
              <span className="rail__mark" aria-hidden="true">✓</span>
              <span className="rail__label">Условия</span>
            </a>
          </li>
          {STAGES.map((stage, position) => {
            const state = stageStateOf(run, stage.id);
            return (
              <li
                key={stage.id}
                className={`rail__item rail__item--${state} ${active === stage.id ? "rail__item--active" : ""}`}
                data-band={position + 1}
              >
                <a className="rail__link" href={`#${stage.id}`}>
                  <span className="rail__order">{position + 1}</span>
                  <span className="rail__mark" aria-hidden="true">{STATE_MARK[state]}</span>
                  <span className="rail__label">{stage.label}</span>
                  {payload && state === "done" ? <LampDot state={stage.lamp(payload)} /> : null}
                </a>
              </li>
            );
          })}
        </ol>
      </RailGroup>

      <RailGroup title="Ключевые числа">
        {numbers.length > 0 ? (
          <RailLines lines={numbers} />
        ) : (
          <p className="rail__empty">появятся по ходу прогона</p>
        )}
      </RailGroup>

      <RailGroup title="Источники">
        {sources.length > 0 ? (
          <ul className="rail__sources">
            {sources.map((source) => (
              <li key={source.name} className="rail__source">
                <LampDot state={source.usable ? "pass" : "fail"} />
                <span className="rail__source-name">{source.name}</span>
                <span className="rail__source-age">{source.age}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rail__empty">вердикты по источникам не передавались</p>
        )}
      </RailGroup>

      <RailGroup title="Агенты">
        {agents.length > 0 ? (
          <RailLines lines={agents} />
        ) : (
          <p className="rail__empty">трасса ещё не пришла</p>
        )}
      </RailGroup>
    </aside>
  );
}
