import type { MomentView } from "./moment";
import { KIND_LABEL, longMoment } from "./moment";
import "./history.css";

interface Props {
  moment: MomentView | null;
  open: boolean;
  disabled?: boolean;
  onToggle: () => void;
  controls?: string;
}

/** Компактная строка «Данные для расчёта»: дата видна всегда, выбор открывается по «Изменить». */
export function MomentSummary({ moment, open, disabled, onToggle, controls }: Props) {
  return <div className="moment-row">
    <span className="moment-row__kicker">Данные для расчёта</span>
    <div className="moment-row__main">
      <strong className="moment-row__date">{moment?.kind === "scenario" ? "Сценарные данные" : moment ? longMoment(moment.at) : "момент не выбран"}</strong>
      {moment ? <span className={`moment-row__kind moment-row__kind--${moment.kind}`}>{KIND_LABEL[moment.kind]}</span> : null}
      {moment?.label ? <span className="moment-row__label">эпизод «{moment.label}»</span> : null}
    </div>
    <button type="button" className="moment-row__change" disabled={disabled} aria-expanded={open}
      aria-controls={controls} onClick={onToggle}>
      {open ? "Свернуть" : "Изменить"} <span aria-hidden="true">{open ? "↑" : "→"}</span>
    </button>
  </div>;
}
