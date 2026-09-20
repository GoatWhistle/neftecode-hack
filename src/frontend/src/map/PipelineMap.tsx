import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ORDER, reachedState } from "../run/sequence";
import { STATE_WORD } from "../run/railStatus";
import type { RunState, StageState } from "../run/types";
import { useLiveClock } from "../useLiveClock";
import { spanText } from "../format";
import { activeExitEdge } from "./exits";
import type { MapNode } from "./graph";
import { MAP_NODES, TERMINAL_HOLD, TERMINAL_RECOMMEND, TERMINAL_REFUSE, nodeById } from "./graph";
import { mapRows, useMapColumns } from "./layout";
import { InputNode } from "./InputNode";
import { StageNode } from "./StageNode";
import type { TerminalState } from "./TerminalNode";
import { TerminalNode } from "./TerminalNode";
import { useNodeRects } from "./useNodeRects";
import type { WireState } from "./WireLayer";
import { WireLayer } from "./WireLayer";
import type { Wire } from "./wires";
import { buildWires } from "./wires";
import { Drawer } from "./Drawer";
import { focusNode, scrollToSummary, spentOf, usePrinting } from "./mapRuntime";
import { scrollToDrawer } from "../run/autoscroll";

export interface PipelineMapProps {
  run: RunState;
  inputCaption: string;
  open: string | null;
  onOpen: (id: string | null) => void;
}

const TERMINAL_BY_STATUS: Record<string, string> = {
  hold: TERMINAL_HOLD,
  recommend_scenario: TERMINAL_RECOMMEND,
  refuse: TERMINAL_REFUSE
};

export const PANEL_ID = "map-drawer";

const ARROW_NEXT = new Set(["ArrowRight", "ArrowDown"]);
const ARROW_PREV = new Set(["ArrowLeft", "ArrowUp"]);

export function PipelineMap({ run, inputCaption, open, onOpen }: PipelineMapProps) {
  const [board, setBoard] = useState<HTMLDivElement | null>(null);
  const measured = useNodeRects(board);
  const screenColumns = useMapColumns();
  const printing = usePrinting();
  const columns = printing ? 1 : screenColumns;
  const wires = useMemo(() => buildWires(measured, columns), [measured, columns]);
  const liveMs = useLiveClock(run.elapsedMs, run.lastFrameAt, run.status === "running" && run.live);
  const started = run.status !== "idle";
  const status = run.payload?.decision.status ?? null;
  const takenTerminal = status ? (TERMINAL_BY_STATUS[status] ?? null) : null;
  const exitEdge = activeExitEdge(run.payload);
  const rows = mapRows(columns);

  const stateOfNode = useCallback(
    (id: string): StageState => reachedState(run.stages, id),
    [run.stages]
  );

  const lastOpen = useRef<string | null>(null);

  useEffect(() => {
    if (open === null && lastOpen.current !== null && board) {
      focusNode(board, lastOpen.current);
    }
    lastOpen.current = open;
  }, [open, board]);

  const remeasure = useCallback(
    (event: React.TransitionEvent<HTMLDivElement>) => {
      window.dispatchEvent(new Event("resize"));
      if (printing) return;
      if (event.currentTarget.dataset["open"] === "true") scrollToDrawer(PANEL_ID);
    },
    [printing]
  );

  const onBoardKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!ARROW_NEXT.has(event.key) && !ARROW_PREV.has(event.key)) return;
      const current = (event.target as HTMLElement).dataset["mapNode"];
      if (!current) return;
      const at = ORDER.indexOf(current);
      if (at === -1) return;
      const step = ARROW_NEXT.has(event.key) ? 1 : -1;
      const next = ORDER[at + step];
      if (!next || !board) return;
      event.preventDefault();
      focusNode(board, next);
    },
    [board]
  );

  const wireState = useCallback(
    (wire: Wire): WireState => {
      if (wire.kind === "exit") {
        return wire.id === exitEdge ? "alert" : "idle";
      }
      if (wire.kind === "loop" || wire.kind === "back") return "idle";
      const from = stateOfNode(wire.from);
      if (wire.from === "decision") {
        return wire.to === takenTerminal && from === "done" ? "drawn" : "idle";
      }
      if (wire.from.startsWith("in-")) {
        return started ? "drawn" : "idle";
      }
      return from === "done" || from === "failed" ? "drawn" : "idle";
    },
    [exitEdge, stateOfNode, started, takenTerminal]
  );

  const terminalState = (id: string): TerminalState => {
    if (id !== takenTerminal) return "idle";
    return id === TERMINAL_REFUSE ? "refused" : "taken";
  };

  const pick = useCallback(
    (id: string) => {
      if (id === "decision") {
        scrollToSummary();
        return;
      }
      onOpen(open === id ? null : id);
    },
    [onOpen, open]
  );

  const renderNode = (node: MapNode) => {
    if (node.kind === "input") {
      return <InputNode key={node.id} node={node} caption={inputCaption} />;
    }
    if (node.kind === "terminal") {
      return (
        <TerminalNode
          key={node.id}
          node={node}
          state={terminalState(node.id)}
          onSelect={run.payload ? scrollToSummary : undefined}
        />
      );
    }
    const state = stateOfNode(node.id);
    return (
      <StageNode
        key={node.id}
        node={node}
        state={state}
        spentMs={spentOf(run, node.id, state, liveMs)}
        run={run}
        liveMs={liveMs}
        started={started}
        expanded={open === node.id}
        panelId={node.id === "decision" ? undefined : PANEL_ID}
        onSelect={pick}
      />
    );
  };

  return (
    <section
      className="map"
      aria-label="Схема расчёта"
      style={{ "--map-columns": columns } as CSSProperties}
    >
      <div className="map__board" ref={setBoard} onKeyDown={onBoardKeyDown}>
        <WireLayer
          wires={wires}
          width={measured.width}
          height={measured.height}
          stateOf={wireState}
        />
        {rows.map((row, index) => {
          const rowOpen = row.cells.find((id) => (printing ? id !== "decision" : id === open));
          const showContour = index === 0 || rows[index - 1]?.contour !== row.contour;
          return (
            <div key={row.key} className="map__band">
              <div className={`map__row map__row--${row.direction}`}>
                {showContour ? <p className="label map__contour">{row.contour}</p> : null}
                <div className="map__cells">
                  {row.cells.map((id) => {
                    const node = nodeById(id);
                    return node ? renderNode(node) : null;
                  })}
                  {row.terminals ? (
                    <div className="map__terminals">
                      {row.terminals.map((id) => {
                        const node = nodeById(id);
                        return node ? renderNode(node) : null;
                      })}
                    </div>
                  ) : null}
                </div>
              </div>
              <div
                className="map__slot"
                data-open={rowOpen !== undefined}
                onTransitionEnd={remeasure}
              >
                {rowOpen !== undefined ? (
                  <Drawer
                    id={rowOpen}
                    panelId={PANEL_ID}
                    run={run}
                    state={stateOfNode(rowOpen)}
                    onClose={() => onOpen(null)}
                    focusOnMount={!printing}
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <ol className="sr-only">
        {MAP_NODES.filter((node) => node.kind === "stage").map((node) => {
          const state = stateOfNode(node.id);
          const spent = spentOf(run, node.id, state, liveMs);
          return (
            <li key={node.id}>
              {`этап ${node.order} из 8, ${node.label}, ${STATE_WORD[state]}`}
              {spent === null ? "" : `, ${spanText(spent)}`}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
