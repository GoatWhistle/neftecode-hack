import type { CSSProperties, ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import { ORDER, reachedState } from "../run/sequence";
import type { RunState, StageState } from "../run/types";
import { useLiveClock } from "../useLiveClock";
import { activeExitEdge } from "./exits";
import type { MapNode } from "./graph";
import { INPUT_SCENARIO, TERMINAL_HOLD, TERMINAL_RECOMMEND, TERMINAL_REFUSE } from "./graph";
import { mapLanes, useMapColumns } from "./layout";
import { InputNode } from "./InputNode";
import { StageNode } from "./StageNode";
import type { TerminalState } from "./TerminalNode";
import { TerminalNode } from "./TerminalNode";
import { useNodeRects } from "./useNodeRects";
import type { WireState } from "./WireLayer";
import { WireLayer } from "./WireLayer";
import type { Wire } from "./wires";
import { buildWires } from "./wires";
import { INPUT_PANEL_ID } from "./InputSlot";
import { MapBand, PANEL_ID } from "./MapBand";
import { MapOutline } from "./MapOutline";
import { focusNode, scrollToSummary, spentOf, usePrinting } from "./mapRuntime";
import { useDrawerSlot } from "./useDrawerSlot";

export interface PipelineMapProps {
  run: RunState;
  inputCaption: string;
  open: string | null;
  onOpen: (id: string | null) => void;
  inputPanel?: ReactNode;
  inputMeta?: string;
}

const TERMINAL_BY_STATUS: Record<string, string> = {
  hold: TERMINAL_HOLD,
  recommend_scenario: TERMINAL_RECOMMEND,
  refuse: TERMINAL_REFUSE
};

export { PANEL_ID };

const ARROW_NEXT = new Set(["ArrowRight", "ArrowDown"]);
const ARROW_PREV = new Set(["ArrowLeft", "ArrowUp"]);

const WALK = [INPUT_SCENARIO, ...ORDER];

export function PipelineMap({
  run,
  inputCaption,
  open,
  onOpen,
  inputPanel,
  inputMeta
}: PipelineMapProps) {
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
  const lanes = mapLanes(columns);

  const stateOfNode = useCallback(
    (id: string): StageState => reachedState(run.stages, id),
    [run.stages]
  );

  const stageOpen = open === INPUT_SCENARIO ? null : open;
  const inputOpen = open === INPUT_SCENARIO ? open : null;
  const { shown, onSlotTransitionEnd } = useDrawerSlot(stageOpen, board, PANEL_ID, printing);
  const { shown: shownInput, onSlotTransitionEnd: onInputTransitionEnd } = useDrawerSlot(
    inputOpen,
    board,
    INPUT_PANEL_ID,
    printing
  );

  const onBoardKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!ARROW_NEXT.has(event.key) && !ARROW_PREV.has(event.key)) return;
      const current = (event.target as HTMLElement).dataset["mapNode"];
      if (!current) return;
      const at = WALK.indexOf(current);
      if (at === -1) return;
      const step = ARROW_NEXT.has(event.key) ? 1 : -1;
      const next = WALK[at + step];
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
      if (!inputPanel) return <InputNode key={node.id} node={node} caption={inputCaption} />;
      return (
        <InputNode
          key={node.id}
          node={node}
          caption={inputCaption}
          locked={started}
          expanded={open === node.id}
          panelId={INPUT_PANEL_ID}
          onSelect={pick}
        />
      );
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
        {lanes.map((lane) => (
          <div key={lane.key} className="map__lane" data-tone={lane.tone}>
            <p className="map__contour">{lane.contour}</p>
            <div className="map__lane-body">
              {lane.rows.map((row) => (
                <MapBand
                  key={row.key}
                  row={row}
                  run={run}
                  printing={printing}
                  stageOpen={stageOpen}
                  shown={shown}
                  inputOpen={inputOpen}
                  shownInput={shownInput}
                  inputPanel={inputPanel}
                  inputMeta={inputMeta ?? ""}
                  stateOf={stateOfNode}
                  renderNode={renderNode}
                  onClose={() => onOpen(null)}
                  onSlotTransitionEnd={onSlotTransitionEnd}
                  onInputTransitionEnd={onInputTransitionEnd}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <MapOutline run={run} liveMs={liveMs} stateOf={stateOfNode} />
    </section>
  );
}
