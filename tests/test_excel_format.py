"""Zeitformat im Stundenzettel: Industriezeit oder Std:Min (Excel-Zeit) und Runden auf Minutenschritte."""
from datetime import date, timedelta

import pytest

from workplanner.excel_timesheet import (TIME_FORMAT, DayHours, Plan, PlanLine, aggregate, apply_plan, hours_text,
                                         round_minutes)

DAY = date(2026, 11, 2)


def rows(*minutes):
    return [{"kind": "work", "date": DAY, "project": "Demo", "project_number": "1",
             "duration": timedelta(minutes=m)} for m in minutes]


@pytest.mark.parametrize("minutes,step,expected", [(108, 5, 110), (107, 5, 105), (107.5, 5, 110), (62, 15, 60),
                                                    (68, 15, 75), (61.4, 1, 61), (61.4, 0, 61.4)])
def test_round_minutes(minutes, step, expected):
    assert round_minutes(minutes, step) == pytest.approx(expected)


def test_industrial_value_is_rounded_to_five_minutes_then_two_decimals():
    assert aggregate(rows(108), step_minutes=5)[0].hours == 1.83          # 1:48 → 1:50 → 1,83
    assert aggregate(rows(107), step_minutes=5)[0].hours == 1.75          # 1:47 → 1:45
    assert aggregate(rows(75))[0].hours == 1.25                           # 1:15 ohne Runden wie bisher


def test_rounding_applies_to_the_sum_of_a_project_per_day():
    assert aggregate(rows(21, 21, 21), step_minutes=5)[0].hours == 1.08   # 63 min → 65 min (nicht 3 × 20)


def test_time_format_keeps_exact_minutes_and_marks_the_items():
    item = aggregate(rows(110), step_minutes=5, as_time=True)[0]
    assert item.as_time and item.hours == pytest.approx(110 / 60)
    assert hours_text(item.hours, True) == "1:50" and hours_text(1.83) == "1.83"


class Sheet:
    def __init__(self):
        self.name = "Nov"
        self.values, self.formats = {}, {}

    def set_value(self, row, col, value):
        self.values[row, col] = value

    def set_number_format(self, row, col, fmt):
        self.formats[row, col] = fmt


class Book:
    def __init__(self, sheet):
        self._sheet = sheet

    def sheet(self, name):
        return self._sheet


def test_time_value_is_written_as_fraction_of_a_day_with_hour_minute_format():
    sheet = Sheet()
    line = PlanLine("Nov", DAY, "Demo", 1 + 50 / 60, 8, 6, None, "vorhanden", as_time=True)
    apply_plan(Book(sheet), Plan(lines=[line]))
    assert sheet.formats[8, 6] == TIME_FORMAT == "[h]:mm"
    assert sheet.values[8, 6] == pytest.approx((1 + 50 / 60) / 24)


def test_industrial_value_is_written_unchanged_without_touching_the_format():
    sheet = Sheet()
    apply_plan(Book(sheet), Plan(lines=[PlanLine("Nov", DAY, "Demo", 1.83, 8, 6, None, "vorhanden")]))
    assert sheet.values[8, 6] == 1.83 and not sheet.formats


def test_overwrite_check_compares_in_the_chosen_format():
    t = 110 / 60
    same = PlanLine("Nov", DAY, "Demo", t, 8, 6, t / 24, "vorhanden", as_time=True)
    other = PlanLine("Nov", DAY, "Demo", t, 8, 6, 1 / 24, "vorhanden", as_time=True)
    assert not same.overwrites and other.overwrites


def test_service_settings_default_and_validation():
    from workplanner.db import Database
    from workplanner.service import TimeService
    svc = TimeService(Database())
    assert svc.excel_time_format == "decimal" and svc.excel_round_minutes == 5
    svc.set_excel_format("time", 15)
    assert svc.excel_time_format == "time" and svc.excel_round_minutes == 15
    svc.set_excel_format("quatsch", 7)                                    # ungültig: Standard
    assert svc.excel_time_format == "decimal" and svc.excel_round_minutes == 5
