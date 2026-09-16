"""Parsing the published formulas, and refusing to compute the ones whose inputs are unbound."""
import numpy as np
import pandas as pd
import pytest

from neftecode.evaluation.vak import (AVT_CFPP_FIX, CORRECTED, UNBOUND_LAB_INPUTS, VakError,
                                      check_formula, evaluate, normalise, parse_formula,
                                      ratio_features)


def formula(text, name="24-2000:GODT:Test", group="24-2000"):
    return parse_formula(name, text, group)


# --- Notation is normalised without changing meaning ---

def test_decimal_comma_becomes_a_point():
    assert normalise("791,22872 + 1") == "791.22872 + 1"


def test_letter_x_between_operands_means_multiplication():
    assert normalise("0,52755xT66") == "0.52755*T66"
    assert normalise("5,30294x(F30)") == "5.30294*(F30)"


def test_cyrillic_x_is_also_multiplication():
    assert normalise("0,5х T66") == "0.5*T66"


def test_empty_formula_is_refused():
    with pytest.raises(VakError, match="Пустой текст"):
        normalise("   ")


# --- The published bracket error is removed, not reinterpreted ---

def test_avt_cfpp_uses_the_official_denominator_of_2026_09_16():
    parsed = formula("31,40363 - 0,47309x(F65/F32+ F30))", "AVT6:240-350:CFPP")
    assert parsed.expression == AVT_CFPP_FIX
    assert "F65/(F32 + F30)" in parsed.expression


def test_official_file_supersedes_the_workbook_text():
    from neftecode.evaluation.vak import PUBLISHED_2026_09_16

    for name, text in PUBLISHED_2026_09_16.items():
        parsed = parse_formula(name, "1 + F30", "AVT6")
        assert parsed.expression == text and parsed.corrected
    assert "+ 0.76664*T6" in parse_formula("AVT6:350:I350", "-0.76664*T6", "AVT6").expression


def test_unclosed_bracket_is_an_error():
    with pytest.raises(VakError, match="Незакрытые скобки"):
        formula("1 + (F1")


# --- Expert corrections are applied ---

def test_every_corrected_formula_uses_the_expert_text():
    for name in CORRECTED:
        assert parse_formula(name, "0", "24-2000").corrected is True


def test_t90_correction_divides_the_quench_flow_by_two_thousand():
    parsed = parse_formula("24-2000:GODT:T90", "162.998+59.57*F15", "24-2000")
    assert "F15/2000" in parsed.expression


def test_cloud_point_correction_gives_f22_its_coefficient():
    parsed = parse_formula("24-2000:GODT:CloudPoint", "F22+0.0021*W7", "24-2000")
    assert parsed.expression.startswith("0.0002*F22")


# --- Unbound laboratory inputs make a formula uncomputable ---

def test_formula_needing_an_unbound_lab_point_is_not_computable():
    parsed = parse_formula("24-2000:GODT:T95", "0", "24-2000")
    assert parsed.computable is False
    assert parsed.unbound == ("LIMSPipelineTninetyfive",)


def test_evaluating_an_uncomputable_formula_raises_instead_of_guessing():
    parsed = parse_formula("24-2000:GODT:T95", "0", "24-2000")
    with pytest.raises(VakError, match="не привязаны входы"):
        evaluate(parsed, pd.DataFrame({"ht.F9": [1.0]}))


def test_uncomputable_formula_reports_unavailable_with_the_reference_name():
    published = "667.881+0.15417*LIMS:24-2000.Pipeline.D15+0.00005*F22+0.10774*T11"
    parsed = parse_formula("24-2000:GODT:D15", published, "24-2000")
    assert parsed.computable is False
    check = check_formula(parsed, pd.DataFrame(), None)
    assert check.status == "unavailable"
    assert UNBOUND_LAB_INPUTS["LIMSPipelineDensity15"] in check.reason


# --- Only arithmetic is allowed ---

@pytest.mark.parametrize("text", ["__import__('os')", "F1.real", "abs(F1)", "F1 if F2 else F3"])
def test_non_arithmetic_constructs_are_refused(text):
    with pytest.raises(VakError):
        formula(text)


# --- Evaluation ---

def frame(**columns):
    return pd.DataFrame(columns, index=pd.date_range("2026-01-01", periods=len(next(iter(columns.values()))), freq="10min"))


def test_evaluation_matches_hand_computation():
    parsed = formula("2*F1 + 3")
    got = evaluate(parsed, frame(**{"ht.F1": [1.0, 2.0, 4.0]}))
    assert list(got) == [5.0, 7.0, 11.0]


def test_vanishing_denominator_gives_unknown_not_a_huge_number():
    parsed = formula("F1/F2")
    got = evaluate(parsed, frame(**{"ht.F1": [1.0, 1.0], "ht.F2": [2.0, 0.0]}))
    assert got[0] == 0.5
    assert np.isnan(got[1]), "деление на нуль обязано давать неизвестность, а не бесконечность"


def test_missing_tag_is_reported_by_name():
    parsed = formula("F1 + F99")
    with pytest.raises(VakError, match="ht.F99"):
        evaluate(parsed, frame(**{"ht.F1": [1.0]}))


def test_prefix_follows_the_unit_of_the_formula():
    parsed = parse_formula("AVT6:240-350:T50", "2*F7", "ЭЛОУ-АВТ-6. 240-350")
    got = evaluate(parsed, frame(**{"avt.F7": [3.0]}))
    assert got[0] == 6.0


# --- Ratios become guarded features ---

def test_ratios_are_extracted_from_the_published_text():
    parsed = formula("424.72638*F1/F26 + F15/2000")
    assert "F1/F26" in parsed.ratios


def test_ratio_features_protect_the_denominator():
    parsed = {"f": formula("F1/F26")}
    signals = frame(**{"ht.F1": [1.0, 2.0], "ht.F26": [2.0, 0.0]})
    features = ratio_features(parsed, signals)
    column = features["vak.ht.F1_over_F26"]
    assert column.iloc[0] == 0.5
    assert np.isnan(column.iloc[1])


def test_ratio_feature_is_skipped_when_a_tag_is_absent():
    assert ratio_features({"f": formula("F1/F99")}, frame(**{"ht.F1": [1.0]})).empty


# --- Checking against the laboratory ---

def lab(values, start="2026-01-01", freq="6h"):
    return pd.DataFrame({"time": pd.date_range(start, periods=len(values), freq=freq), "value": values})


def test_check_reports_error_period_and_sample_count():
    signals = frame(**{"ht.F1": np.linspace(1, 2, 600)})
    parsed = formula("10*F1")
    measured = lab(list(np.linspace(10, 20, 40)), freq="100min")
    check = check_formula(parsed, signals, measured)
    assert check.status == "checked"
    assert check.n >= 30
    assert check.mae is not None and check.correlation is not None
    assert check.first_sample and check.last_sample


def test_too_few_matched_samples_leaves_the_formula_unchecked():
    signals = frame(**{"ht.F1": np.linspace(1, 2, 600)})
    check = check_formula(formula("10*F1"), signals, lab([10.0, 11.0, 12.0], freq="100min"))
    assert check.status == "unchecked"
    assert "мало" in check.reason


def test_absent_laboratory_series_leaves_the_formula_unchecked():
    check = check_formula(formula("10*F1"), frame(**{"ht.F1": [1.0]}), None)
    assert check.status == "unchecked"
    assert check.mae is None


def test_every_check_carries_the_no_causality_note():
    signals = frame(**{"ht.F1": np.linspace(1, 2, 600)})
    for check in (check_formula(formula("10*F1"), signals, lab(list(np.linspace(10, 20, 40)), freq="100min")),
                  check_formula(formula("10*F1"), signals, None),
                  check_formula(parse_formula("24-2000:GODT:T95", "0", "24-2000"), signals, None)):
        assert any("не доказательство причинности" in note for note in check.limitations)
