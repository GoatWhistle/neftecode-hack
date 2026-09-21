import { useId, useState } from "react";
import type { ScreenPayload } from "../types";
import { num } from "../format";
import { compareModel } from "./rows";
import type { CompareCell, CompareRow } from "./rows";

export interface PlanCompareProps {
  payload: ScreenPayload;
}

function Num({ cell }: { cell: CompareCell }) {
  if (!cell.known) return <span className="cmp__void">нет оценки</span>;
  return <span className="cmp__figure">{cell.text}</span>;
}

function Row({ row }: { row: CompareRow }) {
  return (
    <tr className={`cmp__row cmp__row--${row.role}`}>
      <th scope="row" className="cmp__head">
        <span className="cmp__action">{row.action}</span>
        <code className="cmp__id">{row.id}</code>
        {row.role === "selected" ? <span className="cmp__pick">выбран</span> : null}
      </th>
      <td className="cmp__cell"><Num cell={row.production} /></td>
      <td className="cmp__cell"><Num cell={row.cost} /></td>
      <td className="cmp__cell"><Num cell={row.severity} /></td>
      <td className="cmp__cell"><Num cell={row.changes} /></td>
      <td className="cmp__why">{row.why}</td>
    </tr>
  );
}

export function PlanCompare({ payload }: PlanCompareProps) {
  const model = compareModel(payload);
  const [open, setOpen] = useState(false);
  const noteId = useId();

  const horizon = model.horizonHours !== null
    ? `${num(model.horizonHours, 2)} ч`
    : "горизонт не передан";

  return (
    <section className="cmp" aria-labelledby={`${noteId}-t`}>
      <h3 className="cmp__rubric" id={`${noteId}-t`}>Почему этот вариант</h3>

      {model.blocked !== null ? (
        <p className="cmp__blocked">{model.blocked}</p>
      ) : (
        <>
          <div className="cmp__frame" role="group" tabIndex={0} aria-label="Сравнение планов">
            <table className="cmp__table">
              <thead>
                <tr>
                  <th scope="col">Действие</th>
                  <th scope="col">Выпуск<span className="cmp__unit">т за {horizon}</span></th>
                  <th scope="col">Стоимостный прокси<span className="cmp__unit">у.е./т</span></th>
                  <th scope="col">Прокси-тяжесть<span className="cmp__unit">индекс, безразмерный</span></th>
                  <th scope="col">Изменений<span className="cmp__unit">уставок от текущего режима</span></th>
                  <th scope="col">Причина выбора или отклонения</th>
                </tr>
              </thead>
              <tbody>
                {model.rows.map((row) => <Row key={row.key} row={row} />)}
              </tbody>
            </table>
          </div>

          {!model.paired ? (
            <p className="cmp__blocked">
              Парного сравнения нет: альтернатив в результате не передано. Показаны только показатели
              выбранного плана — это не значит, что других вариантов не рассматривали.
            </p>
          ) : null}
        </>
      )}

      <div className="cmp__foot">
        <button
          type="button"
          className="cmp__more"
          aria-expanded={open}
          aria-controls={noteId}
          onClick={() => setOpen((prev) => !prev)}
        >
          <span className="cmp__caret" aria-hidden="true" />
          Правило сравнения и происхождение чисел
        </button>
        <div id={noteId} className="cmp__panel" data-open={open ? "yes" : "no"}>
          <div className="cmp__panelin">
            {model.rule !== null ? (
              <p className="cmp__rule">{model.rule}</p>
            ) : (
              <p className="cmp__rule">
                Правило ранжирования в этом результате не передано. Порядок предпочтения по тексту
                интерфейса не восстанавливаем.
              </p>
            )}
            <dl className="cmp__src">
              <div><dt>Выпуск</dt><dd><code>decision.production_t</code>, т</dd></div>
              <div><dt>Стоимостный прокси</dt><dd><code>decision.cost_per_tonne</code>, у.е./т сценария — не рубли, реальных цен нет</dd></div>
              <div><dt>Прокси-тяжесть</dt><dd><code>decision.severity_index</code>, сводный безразмерный индекс</dd></div>
              <div><dt>Изменений</dt><dd><code>decision.selected_plan.changes</code>, штук</dd></div>
              <div><dt>Строки альтернатив</dt><dd><code>explanation.alternatives[]</code> целиком, вместе с готовым <code>why_not</code></dd></div>
              <div>
                <dt>Горизонт выпуска</dt>
                <dd>
                  {model.horizonSource !== null
                    ? <><code>{model.horizonSource}</code>, {horizon}. Все четыре показателя взяты на одном горизонте; разные горизонты не вычитаются.</>
                    : "в результате не передан, поэтому подписан как неизвестный, а не подставлен по умолчанию."}
                </dd>
              </div>
            </dl>
            <p className="cmp__hold">{model.holdNote}</p>
            {model.alternativesTotal > model.alternativesShown ? (
              <p className="cmp__hold">
                Показаны ближайшие {model.alternativesShown} из {model.alternativesTotal}, переданных
                в результате. Результат несёт не более пяти — это не полный перечень проверенных планов,
                их число показано на этапе «Кандидаты».
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
