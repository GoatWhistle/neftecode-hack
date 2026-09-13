#!/usr/bin/env bash
# Собирает локальный комплект сдачи. Ничего никуда не отправляет.
#
# В архив входят: исходный код, конфигурации, сценарии, тесты, рабочий контекст, README и
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

rm -rf "$STAGE"
mkdir -p "$STAGE"

echo "Копирование отслеживаемых файлов"
git ls-files -z | tar --null -T - -cf - | tar -x -C "$STAGE"

echo "Копирование результатов прогона"
mkdir -p "$STAGE/artifacts"
for item in report.md metrics.json risk_metrics.json benchmark.json vak_check.json \
            episodes.json scenes.json manifest.json screen.html scenes decision-20260105-080000.json \
            screen-20260105-080000.html; do
  if [ -e "artifacts/$item" ]; then
    cp -R "artifacts/$item" "$STAGE/artifacts/"
  else
    echo "  пропущено (нет файла): artifacts/$item"
  fi
done

echo "Проверка: в комплекте нет тяжёлых исходных данных и кэшей"
for forbidden in task .venv __pycache__ .pytest_cache catboost_info; do
  if find "$STAGE" -name "$forbidden" -print -quit | grep -q .; then
    echo "  ОШИБКА: в комплект попал $forbidden" >&2
    exit 1
  fi
done

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
echo "Отправка организаторам НЕ выполнена и выполняется только вручную."
