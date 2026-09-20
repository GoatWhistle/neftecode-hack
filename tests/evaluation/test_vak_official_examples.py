"""Сверка наших выражений ВАК с контрольными примерами организаторов.

Организаторы приложили к официальному файлу формул (16.09, сообщение 586) пример расчёта для
каждой из 17 формул: значения входов и результат. Это прямой ответ на вопрос команды о
контрольном примере. Тест проверяет, что выражение, которое строит рабочий код, даёт то же
число — то есть что спорные места (расстановка скобок, знаки, делители) прочитаны так же, как
у организаторов, а не так, как нам удобно.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.evaluation.vak import (UNBOUND_LAB_INPUTS, check_all, evaluate, parse_formula,
                                      telemetry_prefix)

FIXTURE = Path(__file__).resolve().parents[2] / "context" / "task-review" / "vak-official-examples.json"
DOCUMENT = json.loads(FIXTURE.read_text())
EXAMPLES = DOCUMENT["examples"]
TOLERANCE = DOCUMENT["tolerance_abs"]


def _compute(example: dict) -> float:
    formula = parse_formula(example["name"], example["workbook_text"], example["group"])
    prefix = telemetry_prefix(example["name"])
    inputs = example["inputs"]
    lab_values = {name: value for name, value in inputs.items() if name in UNBOUND_LAB_INPUTS}
    frame = pd.DataFrame({f"{prefix}.{name}": [value] for name, value in inputs.items()
                          if name not in UNBOUND_LAB_INPUTS})
    return float(evaluate(formula, frame, lab_values=lab_values)[0])


def test_the_fixture_covers_every_published_formula():
    assert len(EXAMPLES) == 17
    assert len({e["name"] for e in EXAMPLES}) == 17


@pytest.mark.parametrize("example", EXAMPLES, ids=[e["name"] for e in EXAMPLES])
def test_our_expression_reproduces_the_official_worked_example(example):
    computed = _compute(example)
    assert computed == pytest.approx(example["expected"], abs=TOLERANCE), (
        f"{example['name']}: официальный пример даёт {example['expected']}, "
        f"наше выражение — {computed:.4f}")


def test_the_disputed_avt_cfpp_denominator_matches_the_official_example():
    """Спорное место: текст 10.09 читался как F65/F32 + F30, официальный файл 16.09 — F65/(F32+F30).

    Пример расчёта организаторов однозначно показывает F65/(F32+F30) = 4.4365 при
    F65 = 789.54, F32 = 79.00, F30 = 98.97. Альтернативное прочтение даёт другое число,
    поэтому тест ловит любую попытку вернуть его.
    """
    example = next(e for e in EXAMPLES if e["name"] == "AVT6:240-350:CFPP")
    inputs = example["inputs"]
    official_ratio = inputs["F65"] / (inputs["F32"] + inputs["F30"])
    earlier_reading = inputs["F65"] / inputs["F32"] + inputs["F30"]
    assert official_ratio == pytest.approx(4.4365, abs=0.001)
    assert earlier_reading != pytest.approx(official_ratio, abs=1.0)
    assert _compute(example) == pytest.approx(example["expected"], abs=TOLERANCE)


def test_supplying_a_lab_value_does_not_bind_the_lab_point():
    """Явная подстановка лабораторного входа не делает формулу источником качества."""
    example = next(e for e in EXAMPLES if e["name"] == "24-2000:GODT:D15")
    formula = parse_formula(example["name"], example["workbook_text"], example["group"])
    assert formula.computable is False
    assert formula.unbound
    assert _compute(example) == pytest.approx(example["expected"], abs=TOLERANCE)


def test_an_unreadable_formula_is_reported_and_never_repaired():
    """Формула с лишней скобкой и без объявленного исправления не считается, а объявляется."""
    rows = [("AVT6:test:Broken", "1 + 0,47309x(F65/F32+F30))", "AVT6:test")]
    report = check_all(rows, {}, pd.DataFrame())
    assert "AVT6:test:Broken" in report["unparsed"]
    assert report["summary"].get("unparsed") == 1
    assert report["formulas"] == {}
