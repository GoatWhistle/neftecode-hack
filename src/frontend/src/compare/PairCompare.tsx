import type { PairComparison } from "../run/pair";
import "../styles/whatif.css";

interface Props {
  comparison: PairComparison;
  labelA: string;
  labelB: string;
}

export function PairCompare({ comparison, labelA, labelB }: Props) {
  const { headline, inputDiff, inputsKnown, hiddenChanges, incomparable, rows, notes, notApplied, identicalInputs } = comparison;
  return (
    <section className="pair" aria-labelledby="pair-title">
      <h3 className="pair__title" id="pair-title">{headline}</h3>
      <div className="pair__inputs">
        <p className="pair__kicker">Что изменено в условиях</p>
        {!inputsKnown ? (
          <p className="pair__warn">Условия одной из записей неизвестны (сервер не передал метаданные): отличия входов не установлены.</p>
        ) : inputDiff.length === 0 && hiddenChanges.length === 0 ? (
          identicalInputs === true ? (
            <p>Эффективные входы совпадают (отпечаток входов одинаков): различие возможно только из-за вариативности расчёта.</p>
          ) : (
            <p className="pair__warn">Запрошенные условия совпадают, но отпечаток входов неизвестен у одной из записей: одинаковость входов не подтверждена.</p>
          )
        ) : (
          <>
            {inputDiff.length > 0 ? (
              <ul className="pair__diff">
                {inputDiff.map((item) => (
                  <li key={item.key}><b>{item.label}:</b> {item.a} → {item.b}</li>
                ))}
              </ul>
            ) : null}
            {hiddenChanges.length > 0 ? (
              <ul className="pair__warn-list">
                {hiddenChanges.map((text) => <li key={text}>{text}: разницу нельзя приписывать вариативности агента или одному изменённому условию.</li>)}
              </ul>
            ) : null}
          </>
        )}
        {notApplied.length > 0 ? (
          <ul className="pair__warn-list">
            {notApplied.map((text) => <li key={text}>Сервер учёл иначе: {text}</li>)}
          </ul>
        ) : null}
      </div>
      {incomparable.length > 0 ? (
        <ul className="pair__warn-list" aria-label="Несопоставимость">
          {incomparable.map((item) => <li key={item.key}>{item.text}</li>)}
        </ul>
      ) : null}
      {notes.map((text) => <p key={text} className="pair__warn">{text}</p>)}
      <div className="pair__wrap">
        <table className="pair__table">
          <thead>
            <tr><th scope="col">Показатель</th><th scope="col">{labelA}</th><th scope="col">{labelB}</th><th scope="col">Разница</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.changed ? "is-changed" : ""}>
                <th scope="row">{row.label}</th>
                <td>{row.a}</td>
                <td>{row.b}</td>
                <td>{row.delta ?? (row.changed === null ? "—" : row.changed ? "изменилось" : "без изменений")}
                  {row.note ? <small className="pair__note">{row.note}</small> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="pair__scope">Сценарное сравнение двух расчётов, не измеренный эффект на заводе. Разница показана только там, где оба значения известны и сопоставимы.</p>
    </section>
  );
}
