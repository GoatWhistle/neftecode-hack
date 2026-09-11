"""Different data problems must produce different, checkable verdicts."""
import pytest

from neftecode.trust import (DataTrustAgent, MISSING, OK, PLACEHOLDER_VALUE, SOURCE_PRIORITY,
                             UNUSABLE, inspect_value)

CFG = {"lab_max_age_hours": 48, "pak_max_age_minutes": 30}


def state(**kw):
    base = {"decision_time": "2026-01-05T08:00:00",
            "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
            "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
            "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0.0}
    return {**base, **kw}


def assess(**kw):
    return DataTrustAgent(CFG).assess(state(**kw))


# --- Fresh data ---

def test_fresh_data_is_usable_and_prefers_the_laboratory():
    report = assess()
    assert report.usable is True
    assert report.primary == "ЛИМС"
    assert report.fallback_mode is False
    assert report.reasons == ()
    assert report.refusal_reason() is None


def test_laboratory_outranks_the_analyzer_even_when_both_are_fresh():
    assert SOURCE_PRIORITY == ("ЛИМС", "ПАК")
    assert assess(pak_value=2.0).primary == "ЛИМС", "приоритет источника не зависит от значения"


# --- Stale laboratory ---

def test_stale_laboratory_loses_trust_and_says_by_how_much():
    report = assess(lab_age_hours=72.0)
    assert report.verdict("ЛИМС").status == UNUSABLE
    assert any("старше допустимых 48" in r for r in report.verdict("ЛИМС").reasons)
    assert report.primary == "ПАК", "устаревшая лаборатория передаёт роль исправному анализатору"
    assert report.usable is True


def test_missing_laboratory_is_missing_not_merely_unusable():
    report = assess(lab_value=None, lab_usable=False)
    assert report.verdict("ЛИМС").status == MISSING
    assert report.primary == "ПАК"


# --- Frozen analyzer ---

def test_frozen_analyzer_is_rejected_and_forces_fallback_mode():
    report = assess(pak_frozen=True)
    assert report.verdict("ПАК").status == UNUSABLE
    assert any("зависание" in r for r in report.verdict("ПАК").reasons)
    assert report.fallback_mode is True
    assert report.primary == "ЛИМС", "исправная лаборатория ещё держит решение"


def test_frozen_analyzer_value_is_not_replaced_with_zero():
    report = assess(pak_frozen=True, pak_value=7.0)
    assert report.verdict("ПАК").value == 7.0
    assert report.verdict("ПАК").usable is False


# --- Conflict between sources ---

def test_conflict_between_sources_is_a_separate_named_reason():
    report = assess(pak_conflict=True)
    assert any("расходится" in r for r in report.verdict("ПАК").reasons)
    assert report.fallback_mode is True


def test_conflict_and_freezing_are_reported_together_not_collapsed():
    report = assess(pak_conflict=True, pak_frozen=True)
    assert len(report.verdict("ПАК").reasons) == 2


# --- Everything broken: refusal must name what is missing ---

def test_refusal_states_the_missing_requirement():
    report = assess(lab_value=None, lab_usable=False, pak_frozen=True, pak_usable=False)
    assert report.usable is False
    assert report.primary is None
    reason = report.refusal_reason()
    assert "лабораторный анализ" in reason
    assert "анализатор" in reason


def test_incomplete_telemetry_blocks_the_decision_even_with_good_quality_sources():
    report = assess(telemetry_missing_fraction=0.8)
    assert report.usable is False
    assert "полная свежая телеметрия" in report.refusal_reason()


@pytest.mark.parametrize("fraction", [-0.01, 1.5, float("nan"), None, "много"])
def test_impossible_missing_fraction_is_refused(fraction):
    report = assess(telemetry_missing_fraction=fraction)
    assert report.usable is False


def test_telemetry_within_tolerance_still_passes():
    assert assess(telemetry_missing_fraction=0.05).usable is True


# --- A source never passes silently ---

def test_unflagged_but_unusable_source_still_produces_a_reason():
    report = assess(pak_usable=False)
    assert report.verdict("ПАК").status == UNUSABLE
    assert report.verdict("ПАК").reasons, "источник не может быть отвергнут без причины"


def test_negative_laboratory_sulfur_is_rejected():
    report = assess(lab_value=-1.0)
    assert report.verdict("ЛИМС").status == UNUSABLE
    assert any("Отрицательная сера" in r for r in report.verdict("ЛИМС").reasons)


# --- 307 and negatives are suspected, not deleted ---

def test_placeholder_value_is_flagged_but_not_removed():
    found = inspect_value("avt.D10", PLACEHOLDER_VALUE)
    assert found is not None
    assert found["value"] == 307.0, "значение сохраняется, а не обнуляется"
    assert "не удаляется" in found["note"]


def test_negative_process_value_is_flagged_without_being_called_an_error():
    found = inspect_value("avt.P44", -0.97)
    assert found is not None
    assert "ошибкой не считается" in found["note"]
    assert found["value"] == -0.97


def test_ordinary_value_raises_no_suspicion():
    assert inspect_value("avt.T55", 381.5) is None


def test_suspect_values_reach_the_report_without_blocking_it():
    report = assess(raw_values={"avt.D10": PLACEHOLDER_VALUE, "avt.T55": 381.5, "ht.F19": -5.0})
    flagged = {item["tag"] for item in report.suspect_values}
    assert flagged == {"avt.D10", "ht.F19"}
    assert report.usable is True, "подозрение само по себе не отменяет решение"


# --- Report shape ---

def test_report_serialises_with_every_status_preserved():
    report = assess(lab_age_hours=72.0, pak_frozen=True)
    data = report.to_dict()
    assert data["usable"] is False
    assert data["sources"]["ЛИМС"]["status"] == UNUSABLE
    assert data["sources"]["ПАК"]["status"] == UNUSABLE
    assert data["refusal_reason"]
    assert data["sources"]["ЛИМС"]["age_hours"] == 72.0


def test_ages_of_critical_dependencies_are_recorded():
    report = assess(lab_age_hours=12.0, pak_age_minutes=20.0)
    assert report.verdict("ЛИМС").age_hours == 12.0
    assert report.verdict("ПАК").age_hours == pytest.approx(20 / 60)
    assert report.verdict("ЛИМС").max_age_hours == 48


def test_four_situations_give_four_different_results():
    """Fresh, stale lab, frozen analyzer and contradiction must not collapse into one answer."""
    fresh = assess()
    stale = assess(lab_age_hours=72.0)
    frozen = assess(pak_frozen=True)
    broken = assess(lab_age_hours=72.0, pak_frozen=True)
    signatures = {(r.usable, r.primary, r.fallback_mode) for r in (fresh, stale, frozen, broken)}
    assert len(signatures) == 4
    assert fresh.primary == "ЛИМС" and stale.primary == "ПАК"
    assert frozen.primary == "ЛИМС" and broken.primary is None


def test_status_ok_is_only_granted_with_no_reasons():
    assert assess().verdict("ПАК").status == OK
    assert assess().verdict("ПАК").reasons == ()
