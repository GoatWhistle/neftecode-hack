import type { Agentic } from "../types";
import { ROLE_TEXT } from "../run/agentMeters";
import { STATUS_TEXT as LEGACY_STATUS } from "../run/orchRead";
import { Empty, Field, Fields, Note } from "./Primitives";

// Реальные значения agentic.outcome (AgenticMakeDecision._with в decision.py):
// "selected" — агенты выбрали план; "confirmed_legacy" — агенты подтвердили детерминированный план;
// "refused" — агенты дошли до вердикта и отказали; "fallback" — настоящий сбой (провайдер не
// настроен/упал, veto без основания и т.п.); "skipped" — до агентов не дошло (отказ на проверке
// данных). Значения "ok"/"disabled" в backend не существуют и здесь остаются только для обратной
// совместимости со старыми записанными трассами.
const OUTCOMES: Record<string, string> = {
  ok: "живая модель отработала",
  selected: "агенты выбрали план",
  confirmed_legacy: "агенты подтвердили детерминированный план",
  refused: "агенты дошли до отказа",
  fallback: "живая модель не работала, решение принял детерминированный код",
  disabled: "агентный режим выключен",
  skipped: "агенты не привлекались: отказ произошёл раньше, на проверке данных"
};

const MODES: Record<string, string> = {
  agentic: "агентный режим",
  scripted: "детерминированная политика, не LLM",
  off: "агентный режим выключен"
};

// legacy_status — код итога детерминированного ядра (domain/shared/primitives.py: HOLD, RECOMMEND_SCENARIO,
// REFUSE). Человеческая подпись — общий словарь STATUS_TEXT (run/orchRead.ts), код — в JSON ниже по
// странице.

// Backend всегда шлёт agentic.mode = "agentic" (см. AgenticMakeDecision.decide) — mode никогда не
// становится "scripted", реальный признак детерминированного пути — отдельный флаг
// deterministic_policy. И backend никогда не шлёт outcome "ok": настоящие значения после успешного
// прогона — "selected"/"confirmed_legacy"/"refused" с fallback_reason=null. Раньше тон читался как
// `outcome === "ok" ? "live" : "fallback"`, поэтому КАЖДЫЙ обычный завершённый прогон подписывался
// «сработал запасной детерминированный путь», хотя Причина отката оставалась пустой — та самая
// противоречивая пара из finalization-plan.md.
//
// Тон читается по agentic.fallback_reason, а не по конкретному значению outcome: ultrareview нашёл,
// что AgenticMakeDecision._recover_after_agent_failure (decision.py) может вернуть outcome
// "selected"/"refused" (не "fallback") с непустым fallback_reason — когда цикл оркестратора обрывается
// (бюджет исчерпан, исключение, orchestrator_no_final) уже ПОСЛЕ того как специалисты успели наложить
// ограничения/вето; эти ограничения сохраняются, решение пересобирается детерминированно. По
// bacкенд-контракту (`_with` в decision.py) fallback_reason ненулевой ровно тогда, когда что-то пошло
// не так по пути — это и есть надёжный сигнал, а не белый список конкретных outcome-строк.
function toneOf(agentic: Agentic): "live" | "fallback" | "scripted" | "off" | "skipped" {
  if (agentic.outcome === "skipped") return "skipped";
  if (agentic.outcome === "disabled") return "off";
  if (agentic.fallback_reason) return "fallback";
  if (agentic.deterministic_policy || agentic.mode === "scripted") return "scripted";
  return "live";
}

function headline(agentic: Agentic): string {
  const tone = toneOf(agentic);
  if (tone === "live") return "Решение принято с участием живой модели";
  if (tone === "scripted") return "Живая модель не участвовала: детерминированная политика, не LLM";
  if (tone === "off") return "Агентный режим выключен: решение принял детерминированный код без участия LLM";
  if (tone === "skipped") return "Агенты не привлекались: отказ случился раньше, на проверке данных";
  // fallback_reason ненулевой при двух разных ситуациях: живая модель не работала вовсе (opinions
  // пустые) либо специалисты успели высказаться и наложить ограничения/вето до обрыва цикла (opinions
  // непустые) — во втором случае утверждение «живая модель не участвовала» было бы неправдой.
  if ((agentic.opinions ?? []).length > 0) {
    return "Специалисты успели проверить план, но цикл оркестратора оборвался: решение пересобрано " +
      "детерминированно с сохранением их ограничений";
  }
  return "Живая модель не участвовала: сработал запасной детерминированный путь после сбоя провайдера";
}

const VERDICT_TEXT: Record<string, string> = {
  ACCEPT: "принял",
  REVISE: "просил пересмотреть",
  REJECT: "отклонил"
};

// Короткая цепочка для агентного результата (finalization-plan.md, пункт 3): «ядро предложило →
// специалисты проверили → ограничения/вето → итог». Только когда агенты реально дошли до вердикта
// (opinions есть) — не показываем цепочку для fallback/skipped, там и проверять было нечего.
function AgentChain({ agentic }: { agentic: Agentic }) {
  const opinions = agentic.opinions ?? [];
  if (opinions.length === 0) return null;
  const core = agentic.legacy_status ? (LEGACY_STATUS[agentic.legacy_status] ?? agentic.legacy_status) : "—";
  const constraints = agentic.constraints_applied?.length ?? 0;
  const vetoed = Object.keys(agentic.vetoed_candidates ?? {}).length;
  return (
    <ol className="mode__chain">
      <li>
        <b>Ядро предложило</b>
        <span>{core}</span>
      </li>
      <li>
        <b>Специалисты проверили</b>
        <span>
          {opinions
            .map((o) => `${ROLE_TEXT[o.role] ?? o.role} — ${VERDICT_TEXT[o.verdict] ?? o.verdict}`)
            .join("; ")}
        </span>
      </li>
      <li>
        <b>Ограничения и вето</b>
        <span>
          {constraints === 0 && vetoed === 0
            ? "не добавлялись"
            : `ограничений: ${constraints}, планов под вето: ${vetoed}`}
        </span>
      </li>
      <li>
        <b>Итог</b>
        <span>{agentic.final?.summary ?? "не передан"}</span>
      </li>
    </ol>
  );
}

export function AgenticMode({ agentic }: { agentic: Agentic | null }) {
  if (!agentic) {
    return (
      <Empty>
        Режим работы агентов не передавался: по этому экрану нельзя сказать, работала ли живая модель.
      </Empty>
    );
  }

  const tone = toneOf(agentic);

  return (
    <div className={`mode mode--${tone}`}>
      <p className="mode__headline">{headline(agentic)}</p>
      <Fields>
        <Field label="Режим">{MODES[agentic.mode] ?? agentic.mode}</Field>
        <Field label="Исход">{OUTCOMES[agentic.outcome] ?? agentic.outcome}</Field>
        <Field label="Провайдер">{agentic.provider ?? "не задан"}</Field>
        <Field label="Модель">{agentic.model ?? "не задана"}</Field>
        <Field label={tone === "skipped" ? "Почему агенты не привлекались" : "Причина отката"}>
          {agentic.fallback_reason ? (
            <code>{agentic.fallback_reason}</code>
          ) : tone === "skipped" ? (
            "—"
          ) : (
            "отката не было"
          )}
        </Field>
        <Field label="Статус детерминированного пути">
          {agentic.legacy_status
            ? (LEGACY_STATUS[agentic.legacy_status] ?? agentic.legacy_status)
            : "—"}
        </Field>
      </Fields>
      <AgentChain agentic={agentic} />
      {agentic.note ? <Note>{agentic.note}</Note> : null}
    </div>
  );
}
