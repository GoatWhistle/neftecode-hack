import json
import re
from pathlib import Path

COLUMNS = {"К-1", "К-2", "К-10"}
COLORS = {"green", "blue", "yellow", "orange", None}
LEGEND_CONTROLLED = {"green", "blue"}
REQUIRED = ("column", "instrument", "place", "kip_description", "scheme_color", "controlled_by_legend")
TAG_PATTERN = re.compile(r"^[A-Z]\d{1,2}$")


class TagMapError(ValueError):
    pass


def parse_avt_tags(raw: dict) -> dict[str, dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("tags"), dict) or not raw["tags"]:
        raise TagMapError("Карта тегов АВТ: нет раздела tags")
    tags = {}
    for tag, entry in raw["tags"].items():
        where = f"Карта тегов АВТ, {tag}"
        if not TAG_PATTERN.match(tag):
            raise TagMapError(f"{where}: имя тега не похоже на короткий тег CSV")
        if not isinstance(entry, dict):
            raise TagMapError(f"{where}: запись должна быть объектом")
        missing = [key for key in REQUIRED if key not in entry]
        if missing:
            raise TagMapError(f"{where}: нет полей {', '.join(missing)}")
        if entry["column"] not in COLUMNS:
            raise TagMapError(f"{where}: неизвестная колонна {entry['column']!r}")
        if entry["scheme_color"] not in COLORS:
            raise TagMapError(f"{where}: неизвестный цвет {entry['scheme_color']!r}")
        if entry["controlled_by_legend"] is not (entry["scheme_color"] in LEGEND_CONTROLLED):
            raise TagMapError(f"{where}: признак легенды не совпадает с цветом кружка")
        for key in ("instrument", "place", "kip_description"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise TagMapError(f"{where}: поле {key} должно быть непустой строкой")
        tags[tag] = dict(entry)
    return tags


def load_avt_tags(path: Path) -> dict[str, dict]:
    return parse_avt_tags(json.loads(Path(path).read_text(encoding="utf-8")))
