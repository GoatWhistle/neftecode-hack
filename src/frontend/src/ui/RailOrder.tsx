import type { StageState } from "../run/types";

const STATE_TITLE: Record<StageState, string> = {
  pending: "не начат",
  running: "идёт сейчас",
  done: "пройден",
  failed: "отказ"
};

export interface RailOrderProps {
  value: number;
  state: StageState;
}

export function RailOrder({ value, state }: RailOrderProps) {
  return (
    <>
      <span className="rail__order" data-state={state}>
        {value}
      </span>
      <span className="sr-only">{STATE_TITLE[state]}</span>
    </>
  );
}
