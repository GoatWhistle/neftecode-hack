"""The AVT tag map read from the updated schemes, and its use in the virtual-analyser report."""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.evaluation.vak import check_all, input_locations, parse_formula
from neftecode.infrastructure.config.avt_tags import TagMapError, load_avt_tags, parse_avt_tags

MAP_PATH = Path("config/avt_tags.json")

#: The nine AVT formulas exactly as the tag workbook publishes them.
AVT_FORMULAS = [
    ("AVT6:240-350:D15", "791,22872 - 5,30294x(F30/(F32+ F30)) + 0,52755xT66 - 0,15629xT33"),
    ("AVT6:240-350:T50", "283.177+F7*(-0.01685)+0.06248*F30+0.22048*F34-0.25816*F45-0.12159*F59+0.01221*F63"),
    ("AVT6:240-350:EBP", "813.883+2.66463*F30-0.20239*T33-3.65888*F36-14.08235*T37-1.32603*T40+14.60206*T58"),
    ("AVT6:240-350:CFPP", "31,40363 - 0,06784xT33 + 17,411xP67 - 8,11544xP4 - 0,47309x(F65/F32+F30))"),
    ("AVT6:350:T50", "981,06539+ 0,27467xT42 - 0,32983x(F31/F57)  -0,49014xT48"),
    ("AVT6:350:I350", "39.562-1.62865*L43-0.76664*T6-0.22361*T18+0.00031*F64*(T15-T11)"),
    ("AVT6:350:D15", "983.092+0.27467*T42-0.49014*T48-0.32983*F31/F57"),
    ("AVT6:350-500:ViscosityK", "5.831+0.00976*T6+0.01188*T13+0.00224*T18+0.01905*T20+0.00794*L43"
                                "-0.02496*T48-0.00008*P50-0.00882*F53-0.00394*P51-0.00255*F59+0.01153*T61"),
    ("AVT6:350:CFPP", "19,27111 - 0,10582xT48 + 0,13836xT40 - 0,42304x(F31/F57)"),
]


@pytest.fixture(scope="module")
def raw():
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tags():
    return load_avt_tags(MAP_PATH)


def test_every_kip_tag_of_the_avt_unit_is_placed_on_a_scheme(tags):
    assert len(tags) == 71
    numbers = sorted(int(tag[1:]) for tag in tags)
    assert numbers == list(range(1, 72))


def test_legend_marks_exactly_the_blue_and_green_instruments(tags):
    controlled = {tag for tag, entry in tags.items() if entry["controlled_by_legend"]}
    assert controlled == {"P2", "T6", "P22", "F65", "T33", "F19", "F14", "F12", "F64", "F25",
                          "F34", "F32", "F30", "T49", "T37", "F56", "F57", "F59", "F60"}


def test_t55_is_the_vacuum_furnace_not_the_diesel_furnace(tags):
    assert tags["T55"]["column"] == "К-10"
    assert "П-3" in tags["T55"]["place"]
    assert tags["T55"]["controlled_by_legend"] is False


def test_diesel_draws_belong_to_the_atmospheric_column(tags):
    for tag in ("F30", "F32", "W70", "T71", "T66", "T33", "F65"):
        assert tags[tag]["column"] == "К-2"


def test_legend_flag_must_agree_with_the_colour(raw):
    broken = copy.deepcopy(raw)
    broken["tags"]["T1"]["controlled_by_legend"] = True
    with pytest.raises(TagMapError, match="легенды"):
        parse_avt_tags(broken)


def test_unknown_column_and_colour_are_refused(raw):
    wrong_column = copy.deepcopy(raw)
    wrong_column["tags"]["T1"]["column"] = "Р-202"
    with pytest.raises(TagMapError, match="колонна"):
        parse_avt_tags(wrong_column)
    wrong_colour = copy.deepcopy(raw)
    wrong_colour["tags"]["T1"]["scheme_color"] = "red"
    with pytest.raises(TagMapError, match="цвет"):
        parse_avt_tags(wrong_colour)


def test_missing_field_is_refused(raw):
    broken = copy.deepcopy(raw)
    del broken["tags"]["F30"]["place"]
    with pytest.raises(TagMapError, match="place"):
        parse_avt_tags(broken)


def test_every_avt_formula_input_has_a_location(tags):
    for name, text in AVT_FORMULAS:
        located = input_locations(parse_formula(name, text, "AVT6"), tags)
        assert located["unmapped"] == [], name


def test_formula_groups_describe_the_expected_columns(tags):
    d15 = input_locations(parse_formula(*AVT_FORMULAS[0], "AVT6"), tags)
    assert d15["columns"] == ["К-2"]
    t50 = input_locations(parse_formula(*AVT_FORMULAS[4], "AVT6"), tags)
    # F31 is signed on both columns; the map keeps the K-2 reading and says so in a note.
    on_k2 = [tag for tag, place in t50["locations"].items() if place["column"] == "К-2"]
    assert on_k2 == ["F31"] and "К-10" in tags["F31"]["note"]


def test_hydrotreating_formulas_get_no_invented_location(tags):
    located = input_locations(parse_formula("24-2000:GODT:IBP", "137.762-0.0653*F26", "24-2000"), tags)
    assert located["locations"] == {} and "24-2000" in located["note"]


def test_report_carries_locations_only_when_a_map_is_given(tags):
    rows = [(AVT_FORMULAS[0][0], AVT_FORMULAS[0][1], "AVT6")]
    signals = pd.DataFrame({"avt.F30": [1.0], "avt.F32": [1.0], "avt.T66": [1.0], "avt.T33": [1.0]},
                           index=pd.DatetimeIndex(["2025-01-01"]))
    without = check_all(rows, {}, signals)
    assert "input_locations" not in without["formulas"]["AVT6:240-350:D15"]
    with_map = check_all(rows, {}, signals, tag_map=tags)
    located = with_map["formulas"]["AVT6:240-350:D15"]["input_locations"]
    assert located["locations"]["F30"]["controlled_by_legend"] is True


# --- T46: AVT formulas against AVT laboratory points, bound by process position ---

from neftecode.evaluation.vak import AVT_LAB_BINDING  # noqa: E402
from neftecode.infrastructure.data.vak_workbooks import read_avt_points  # noqa: E402


def _avt_case(noise=0.0):
    times = pd.date_range("2025-01-01", periods=60, freq="6h")
    frame = pd.DataFrame({"avt.F30": [100.0 + i for i in range(60)], "avt.F32": [80.0] * 60,
                          "avt.T66": [250.0] * 60, "avt.T33": [338.0] * 60}, index=times)
    formula = parse_formula(*AVT_FORMULAS[0], "AVT6")
    from neftecode.evaluation.vak import evaluate
    lab = pd.DataFrame({"time": times, "value": evaluate(formula, frame) + noise})
    return frame, lab


def test_binding_is_declared_for_the_two_groups_with_laboratory_columns():
    assert {name.rsplit(":", 1)[0] for name in AVT_LAB_BINDING} == {"AVT6:240-350", "AVT6:350"}
    assert {point for point, _ in AVT_LAB_BINDING.values()} == {"avt_1", "avt_3"}
    assert "AVT6:350-500:ViscosityK" not in AVT_LAB_BINDING
    assert AVT_LAB_BINDING["AVT6:240-350:CFPP"] == ("avt_3", "FilterabilityLimit.T")
    assert AVT_LAB_BINDING["AVT6:350:I350"] == ("avt_1", "I350")


def test_avt_check_is_labelled_as_a_hypothesis_and_never_adopted():
    signals, lab = _avt_case()
    rows = [(AVT_FORMULAS[0][0], AVT_FORMULAS[0][1], "AVT6"), (AVT_FORMULAS[7][0], AVT_FORMULAS[7][1], "AVT6")]
    report = check_all(rows, {}, signals, avt_lab={"avt_3": {"D15": lab}, "avt_1": {}})
    checks = {c["name"]: c for c in report["checks"]}
    d15 = checks["AVT6:240-350:D15"]
    assert d15["status"] == "checked" and d15["lab_point"] == "avt_3"
    assert d15["binding"] == "hypothesis_by_process_position"
    assert any("гипотезой" in text for text in d15["limitations"])
    assert checks["AVT6:350-500:ViscosityK"]["status"] == "unchecked"
    assert report["used_as_quality_estimate"] == []
    assert report["avt_binding"]["formulas"]["AVT6:240-350:D15"] == ["avt_3", "D15"]


def test_without_avt_laboratory_the_avt_formulas_stay_unchecked():
    signals, _ = _avt_case()
    report = check_all([(AVT_FORMULAS[0][0], AVT_FORMULAS[0][1], "AVT6")], {}, signals)
    assert report["checks"][0]["status"] == "unchecked"
    assert report["avt_binding"] is None


def test_changed_laboratory_export_is_refused(tmp_path):
    import openpyxl
    book = openpyxl.Workbook()
    book.active.append(["Установка 'Гидроочистка'. Точка отбора '1'."] + [None] * 70)
    path = tmp_path / "lims.xlsx"
    book.save(path)
    with pytest.raises(ValueError, match="Точка отбора '1'"):
        read_avt_points(path)


def test_check_reports_the_error_of_a_constant_median_as_scale():
    signals, lab = _avt_case(noise=0.0)
    report = check_all([(AVT_FORMULAS[0][0], AVT_FORMULAS[0][1], "AVT6")], {}, signals,
                       avt_lab={"avt_3": {"D15": lab}, "avt_1": {}})
    check = report["checks"][0]
    assert check["mae"] == pytest.approx(0.0, abs=1e-9)
    assert check["median_reference_mae"] > 0
