#!/usr/bin/env bash
# Собирает локальный комплект сдачи. Ничего никуда не отправляет.
#
# В архив входят: исходный код, конфигурации, сценарии, тесты, документация и исследования, README и
# результаты прогона из artifacts/. Не входят: выданные данные task/ (331 МБ, условия
# распространения не согласованы), виртуальное окружение, кэши и служебные файлы.
#
# Использование:
#   bash scripts/package.sh [каталог-назначения]

set -euo pipefail
# Не добавлять в tar служебные AppleDouble-файлы `._*` из расширенных атрибутов macOS.
export COPYFILE_DISABLE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$ROOT/dist}"
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="neftecode-$STAMP"
STAGE="$DEST/$NAME"

cd "$ROOT"

echo "Проверка: рабочее дерево без незакоммиченных изменений в отслеживаемых файлах"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "  ВНИМАНИЕ: есть незакоммиченные изменения. Комплект соберётся из рабочего дерева."
fi

if [ -e "$STAGE" ]; then
  echo "ОШИБКА: каталог комплекта уже существует: $STAGE" >&2
  exit 1
fi
mkdir -p "$STAGE"

echo "Копирование отслеживаемых файлов"
python3 scripts/submission_files.py | tar --null -T - -cf - | tar -x -C "$STAGE"

echo "Проверка: обязательные файлы попали в комплект"
MISSING_TRACKED=0
INCOMPLETE_ARTIFACTS=0
for required in README.md pyproject.toml uv.lock .python-version \
                src/frontend/dist/index.html \
                src/frontend/dist/assets/index.js \
                src/frontend/dist/assets/index.css \
                src/neftecode/evaluation/independent.py \
                src/neftecode/evaluation/agent_value.py \
                tests/evaluation/test_independent.py \
                tests/evaluation/test_agent_value.py \
                research/results/independent-evaluation-2026-09-20.json \
                research/results/agent-value-evaluation-2026-09-20.json \
                docs/organizer-clarifications.md; do
  if [ -e "$STAGE/$required" ]; then
    continue
  fi
  echo "  ОШИБКА: обязательный $required отсутствует в отслеживаемом комплекте" >&2
  MISSING_TRACKED=1
done
if [ "$MISSING_TRACKED" -ne 0 ]; then
  echo "  Комплект неполон: соберите недостающие файлы перед сдачей." >&2
  exit 1
fi

echo "Копирование результатов прогона"
mkdir -p "$STAGE/artifacts"
REQUIRED_ARTIFACTS="report.md metrics.json benchmark.json scenes.json manifest.json response_model.json model.pkl screen.json scenes agent-demo.json agent-demo.md source_rules.json"
OPTIONAL_ARTIFACTS="risk_metrics.json vak_check.json episodes.json tank_level_check.json expert_grid.json agent-live-full-20260917.json agent-live-smoke.json agent-live-specialists-20260917.json agent-live-sour_crude-20260920.json audit.jsonl demo.json predictions.csv replay.csv risk_predictions.csv screen.html"
MISSING_REQUIRED=0
for item in $REQUIRED_ARTIFACTS; do
  if [ -e "artifacts/$item" ]; then
    cp -R "artifacts/$item" "$STAGE/artifacts/"
  else
    echo "  ОШИБКА: нет обязательного artifacts/$item" >&2
    MISSING_REQUIRED=1
  fi
done
# Для запуска сохранённых сцен нужен хотя бы один непустой набор срезов.
if [ ! -d "artifacts/snapshots" ] || [ -z "$(find artifacts/snapshots -type f -print -quit 2>/dev/null)" ]; then
  echo "  ОШИБКА: artifacts/snapshots пуст или отсутствует — нет ни одного замороженного среза." >&2
  MISSING_REQUIRED=1
else
  mkdir -p "$STAGE/artifacts/snapshots"
  cp -R "artifacts/snapshots/." "$STAGE/artifacts/snapshots/"
fi
for item in $OPTIONAL_ARTIFACTS; do
  if [ -e "artifacts/$item" ]; then
    cp -R "artifacts/$item" "$STAGE/artifacts/"
  else
    echo "  пропущено (нет файла): artifacts/$item"
  fi
done
for item in artifacts/decision-*.json artifacts/screen-*.json artifacts/screen-*.html; do
  if [ -e "$item" ]; then
    cp -R "$item" "$STAGE/artifacts/"
  fi
done
if [ "$MISSING_REQUIRED" -ne 0 ]; then
  if [ "${ALLOW_INCOMPLETE_ARTIFACTS:-0}" = "1" ]; then
    echo "  ВНИМАНИЕ: обязательные артефакты отсутствуют, сборка продолжена по ALLOW_INCOMPLETE_ARTIFACTS=1." >&2
    echo "            Такой комплект НЕЛЬЗЯ отправлять организаторам." >&2
    INCOMPLETE_ARTIFACTS=1
  else
    echo "  Комплект неполон: соберите артефакты прогоном перед сдачей." >&2
    echo "  Обязательные артефакты строит 'uv run neftecode train' по выданным данным в task/." >&2
    echo "  Чтобы собрать комплект для осмотра (не для сдачи): ALLOW_INCOMPLETE_ARTIFACTS=1 bash scripts/package.sh" >&2
    exit 1
  fi
fi

echo "Проверка: все артефакты из artifacts/ перечислены в списках"
for item in artifacts/*; do
  [ -e "$item" ] || continue
  base="$(basename "$item")"
  case "$base" in
    decision-*.json|screen-*.html|screen-*.json) continue ;;
  esac
  if [ ! -e "$STAGE/artifacts/$base" ]; then
    echo "  ВНИМАНИЕ: artifacts/$base не перечислен в списках и не попал в комплект." >&2
    echo "            Добавьте его в REQUIRED_ARTIFACTS или OPTIONAL_ARTIFACTS." >&2
  fi
done

echo "Проверка: в комплекте нет тяжёлых исходных данных и кэшей"
for forbidden in task .venv __pycache__ .pytest_cache catboost_info node_modules .env .git .claude .idea context AGENTS.md COMPETITORS.md trace.tmp.json; do
  if find "$STAGE" -name "$forbidden" -print -quit | grep -q .; then
    echo "  ОШИБКА: в комплект попал $forbidden" >&2
    exit 1
  fi
done

echo "Проверка: в комплекте нет обращений к внешней сети из HTML и CSS"
EXTERNAL="$(grep -rIl --exclude-dir=.git --include='*.html' --include='*.css' \
  -E '(href|src)=["'"'"']https?://|@import[[:space:]]+(url\()?["'"'"']https?://' "$STAGE" 2>/dev/null || true)"
if [ -n "$EXTERNAL" ]; then
  echo "  ОШИБКА: внешние ресурсы в закрытой сети не загрузятся:" >&2
  echo "$EXTERNAL" >&2
  exit 1
fi

echo "Проверка: в комплекте нет похожего на секреты"
if grep -rIl --exclude-dir=.git -E '(api[_-]?key|secret|password|token)[[:space:]]*[=:][[:space:]]*["'"'"'][^"'"'"']{8,}' "$STAGE" 2>/dev/null | grep -q .; then
  echo "  ОШИБКА: найдено похожее на секрет" >&2
  exit 1
fi

ARCHIVE="$DEST/$NAME.tar.gz"
tar -czf "$ARCHIVE" -C "$DEST" "$NAME"
SIZE="$(du -h "$ARCHIVE" | cut -f1)"

echo
echo "Комплект собран: $ARCHIVE ($SIZE)"
echo "Файлов внутри: $(tar -tzf "$ARCHIVE" | wc -l | tr -d ' ')"
if [ "$INCOMPLETE_ARTIFACTS" -ne 0 ]; then
  echo
  echo "ВНИМАНИЕ: комплект собран БЕЗ обязательных артефактов обучения."
  echo "Это осмотровая сборка. Для сдачи нужен прогон 'uv run neftecode train' по task/."
fi
echo "Отправка организаторам НЕ выполнена и выполняется только вручную."
