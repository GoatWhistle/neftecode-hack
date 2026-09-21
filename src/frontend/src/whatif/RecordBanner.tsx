import type { RecordInfo } from "../run/hydrate";
import { moment } from "../format";
import "../styles/whatif.css";

export function RecordBanner({ info }: { info: RecordInfo }) {
  const who = [info.provider, info.model].filter(Boolean).join(" · ") || "провайдер не указан";
  return (
    <aside className="record-banner" aria-label="Открыта сохранённая запись">
      <strong className="record-banner__badge">Запись</strong>
      <span>расчёт выполнен {moment(info.recordedAt)} · агенты: {who}</span>
      {info.exportedAt ? <span>файл создан {moment(info.exportedAt)}</span> : null}
      <span className="record-banner__note">
        Это сохранённый результат, а не новый расчёт: сервер и языковая модель не вызывались. Кнопка повтора показывает
        события записи ускоренно — это не длительность расчёта.
      </span>
    </aside>
  );
}
