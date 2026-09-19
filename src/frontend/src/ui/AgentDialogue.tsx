import type { AgentEvent } from "../run/types";
import { AGENT_NAMES, KIND_TEXT, groupEvents, summarize } from "../run/agentEvents";
import { JsonPanel } from "./Json";

function Event({ event }: { event: AgentEvent }) {
  return (
    <li className={`dialogue__event dialogue__event--${event.kind}`}>
      <span className="dialogue__seq">{event.seq}</span>
      <div className="dialogue__line">
        <p className="dialogue__kind">
          <b>{AGENT_NAMES[event.agent] ?? event.agent}</b> — {KIND_TEXT[event.kind] ?? event.kind}
        </p>
        <p className="dialogue__summary">{summarize(event)}</p>
        {event.tool_input_summary && event.kind === "tool" ? (
          <p className="dialogue__args">аргументы: <code>{event.tool_input_summary}</code></p>
        ) : null}
        {event.reason_codes && event.reason_codes.length > 0 ? (
          <p className="dialogue__codes">коды причин: {event.reason_codes.join(", ")}</p>
        ) : null}
        {event.tool_result_summary ? (
          <JsonPanel title="что вернул инструмент" value={event.tool_result_summary} openTo={1} />
        ) : null}
      </div>
    </li>
  );
}

export interface AgentDialogueProps {
  events: AgentEvent[];
  running: boolean;
}

export function AgentDialogue({ events, running }: AgentDialogueProps) {
  if (events.length === 0) {
    return (
      <p className="dialogue__empty">
        {running
          ? "Ждём первых событий от агентов: модель уже вызвана."
          : "События агентов по этому прогону не передавались."}
      </p>
    );
  }

  const groups = groupEvents(events);

  return (
    <div className="dialogue">
      <p className="dialogue__counter" role="status">
        Событий получено: {events.length}
        {running ? ", поток продолжается" : ", поток закрыт"}
      </p>
      {groups.map((group) => (
        <section key={group.key} className={`dialogue__group dialogue__group--${group.agent}`}>
          <h4 className="dialogue__title">{group.title}</h4>
          <ol className="dialogue__events">
            {group.events.map((event) => (
              <Event key={event.seq} event={event} />
            ))}
          </ol>
        </section>
      ))}
      {running ? <p className="dialogue__waiting">ждём следующего события…</p> : null}
    </div>
  );
}
