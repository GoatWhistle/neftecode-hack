"""Read the workbook inputs used by the virtual-analyser evaluation."""

from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd


LAB_POINT_COLUMNS = {
    "hydrotreating_2": range(82, 108, 2),
    "avt_1": range(0, 22, 2),
    "avt_3": range(50, 66, 2),
}

#: Header text of the first column of each point; checked so a changed export is not misread.
LAB_POINT_HEADERS = {
    "hydrotreating_2": "Установка 'Гидроочистка'.. Точка отбора '2'.",
    "avt_1": "Установка 'АВТ'. Точка отбора '1'.",
    "avt_3": "Установка 'АВТ'. Точка отбора '3'.",
}


def read_formula_rows(workbook_path: Path) -> list[tuple[str, str, str]]:
    """Return formula name, source text and group without interpreting the formula."""
    book = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    sheet = book["ВАК"]
    rows = list(sheet.values)
    book.close()
    groups = list(rows[0])
    formulas = []
    for row in rows[1:]:
        for index in range(0, len(row) - 1, 2):
            name, source = row[index], row[index + 1]
            if isinstance(name, str) and isinstance(source, str) and ":" in name:
                group = groups[index] if index < len(groups) and groups[index] else name.split(":")[0]
                formulas.append((name, source, str(group)))
    return formulas


def read_lab_point(workbook_path: Path, columns) -> dict[str, pd.DataFrame]:
    """Read independent laboratory series for one declared sampling point."""
    book = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    rows = list(book.active.values)
    book.close()
    names = rows[1]
    series = {}
    for index in columns:
        records = [
            (row[index], row[index + 1])
            for row in rows[4:]
            if isinstance(row[index], datetime) and isinstance(row[index + 1], (int, float))
        ]
        if not records:
            continue
        frame = pd.DataFrame(records, columns=["time", "value"])
        frame["time"] = pd.to_datetime(frame.time)
        series[names[index]] = (
            frame.drop_duplicates("time").sort_values("time").reset_index(drop=True)
        )
    return series


def read_avt_points(workbook_path: Path) -> dict[str, dict[str, pd.DataFrame]]:
    """AVT laboratory points 1 and 3, after checking the export still has them where expected."""
    book = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    header = next(iter(book.active.values))
    book.close()
    for point in ("avt_1", "avt_3"):
        first = LAB_POINT_COLUMNS[point][0]
        if not isinstance(header[first], str) or not header[first].startswith(LAB_POINT_HEADERS[point]):
            raise ValueError(f"ЛИМС: в колонке {first} ожидалась «{LAB_POINT_HEADERS[point]}», "
                             f"найдено {header[first]!r}")
    return {point: read_lab_point(workbook_path, LAB_POINT_COLUMNS[point]) for point in ("avt_1", "avt_3")}


def load_vak_inputs(task_dir: Path) -> tuple[list[tuple[str, str, str]], dict[str, pd.DataFrame]]:
    """Load raw formula rows and laboratory series from the case workbooks."""
    task = Path(task_dir)
    formulas = read_formula_rows(next(task.glob("Теги*.xlsx")))
    lab = read_lab_point(
        next(task.glob("ЛИМС*.xlsx")), LAB_POINT_COLUMNS["hydrotreating_2"]
    )
    return formulas, lab
