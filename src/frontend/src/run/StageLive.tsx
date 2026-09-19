import { LampDot } from "../ui/Primitives";
import type { FactLine, FactSource } from "./stageFacts";
import {
  candidateLines,
  choiceLines,
  forecastLines,
  gateLines,
  inventoryLines,
  trustSources,
  trustVerdict
} from "./stageFacts";
import type { StageFacts } from "./types";

export function FactGrid({ lines }: { lines: FactLine[] }) {
  return (
    <dl className="live__grid">
      {lines.map((line) => (
        <div key={line.label} className={`live__cell live__cell--${line.tone}`}>
          <dt>{line.label}</dt>
          <dd>{line.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function SourceList({ sources }: { sources: FactSource[] }) {
  return (
    <ul className="live__sources">
      {sources.map((source) => (
        <li key={source.name} className="live__source">
          <LampDot state={source.usable ? "pass" : "fail"} />
          <span className="live__source-name">{source.name}</span>
          <span className="live__source-value">{source.value}</span>
          <span className="live__source-age">{source.age}</span>
        </li>
      ))}
    </ul>
  );
}

export function hasLiveFacts(id: string, facts: StageFacts | undefined): boolean {
  if (id === "state") return inventoryLines(facts).length > 0;
  if (id === "trust") return trustSources(facts).length > 0 || trustVerdict(facts).length > 0;
  if (id === "candidates") return candidateLines(facts).length > 0;
  if (id === "forecast") return forecastLines(facts).length > 0;
  if (id === "gate") return gateLines(facts).length > 0;
  if (id === "choice") return choiceLines(facts).length > 0;
  return false;
}

export interface StageLiveProps {
  id: string;
  facts: StageFacts | undefined;
}

export function StageLive({ id, facts }: StageLiveProps) {
  if (id === "state") {
    const lines = inventoryLines(facts);
    if (lines.length === 0) return null;
    return (
      <div className="live">
        <p className="live__caption">Запасы компонентов на момент решения, отметка сервера</p>
        <FactGrid lines={lines} />
      </div>
    );
  }

  if (id === "trust") {
    const sources = trustSources(facts);
    const verdict = trustVerdict(facts);
    if (sources.length === 0 && verdict.length === 0) return null;
    return (
      <div className="live">
        <p className="live__caption">Вердикты по источникам, отметка сервера</p>
        {sources.length > 0 ? <SourceList sources={sources} /> : null}
        {verdict.length > 0 ? <FactGrid lines={verdict} /> : null}
      </div>
    );
  }

  if (id === "candidates") {
    const lines = candidateLines(facts);
    if (lines.length === 0) return null;
    return (
      <div className="live">
        <p className="live__caption">Счётчики перебора, отметка сервера</p>
        <FactGrid lines={lines} />
      </div>
    );
  }

  if (id === "forecast") {
    const lines = forecastLines(facts);
    if (lines.length === 0) return null;
    return (
      <div className="live">
        <p className="live__caption">Расчёт за горизонтом, отметка сервера</p>
        <FactGrid lines={lines} />
      </div>
    );
  }

  if (id === "gate") {
    const lines = gateLines(facts);
    if (lines.length === 0) return null;
    return (
      <div className="live">
        <p className="live__caption">Жёсткие проверки, отметка сервера</p>
        <FactGrid lines={lines} />
      </div>
    );
  }

  if (id === "choice") {
    const lines = choiceLines(facts);
    if (lines.length === 0) return null;
    return (
      <div className="live">
        <p className="live__caption">Итог сравнения планов, отметка сервера</p>
        <FactGrid lines={lines} />
      </div>
    );
  }

  return null;
}
