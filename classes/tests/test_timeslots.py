import datetime
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from classes.models import WeeklyClass
from classes.timeslots import (
    DayOfWeek,
    slot_in_zone,
    slot_to_utc,
    utc_offset_minutes,
)

KARACHI = ZoneInfo("Asia/Karachi")
KOLKATA = ZoneInfo("Asia/Kolkata")
KATHMANDU = ZoneInfo("Asia/Kathmandu")
ADELAIDE = ZoneInfo("Australia/Adelaide")
UTC = datetime.UTC

# Adelaide is +9:30 in its winter and +10:30 under daylight saving.
ADELAIDE_WINTER = datetime.datetime(2026, 7, 1, tzinfo=UTC)
ADELAIDE_SUMMER = datetime.datetime(2027, 1, 15, tzinfo=UTC)

# (zone, moment) pairs the round trip is checked in.
ZONES = [
    pytest.param(KARACHI, None, id="karachi"),
    pytest.param(KOLKATA, None, id="kolkata"),
    pytest.param(KATHMANDU, None, id="kathmandu"),
    pytest.param(ADELAIDE, ADELAIDE_WINTER, id="adelaide-winter"),
    pytest.param(ADELAIDE, ADELAIDE_SUMMER, id="adelaide-summer"),
]


def t(hour, minute=0):
    return datetime.time(hour, minute)


class TestSlotInZone:
    def test_if_utc_evening_returns_next_day_in_karachi(self):
        assert slot_in_zone("monday", t(21), KARACHI) == ("tuesday", t(2))

    def test_if_utc_midday_returns_same_day_in_karachi(self):
        assert slot_in_zone("wednesday", t(10), KARACHI) == ("wednesday", t(15))

    def test_if_last_utc_hour_before_rollover_returns_same_day(self):
        assert slot_in_zone("monday", t(18), KARACHI) == ("monday", t(23))

    def test_if_first_utc_hour_of_rollover_returns_next_day_midnight(self):
        assert slot_in_zone("monday", t(19), KARACHI) == ("tuesday", t(0))

    def test_if_sunday_evening_utc_returns_monday_in_karachi(self):
        # The week wraps: Sunday is the last day code, Monday the first.
        assert slot_in_zone("sunday", t(20), KARACHI) == ("monday", t(1))

    def test_if_time_has_minutes_returns_them_converted(self):
        assert slot_in_zone("monday", t(21, 30), KARACHI) == ("tuesday", t(2, 30))

    def test_if_zone_has_a_half_hour_offset_returns_shifted_minutes(self):
        # Asia/Kolkata is UTC+5:30: the whole time moves, not only the hour.
        assert slot_in_zone("monday", t(18, 45), KOLKATA) == ("tuesday", t(0, 15))

    def test_if_zone_is_utc_returns_the_slot_unchanged(self):
        assert slot_in_zone("sunday", t(23), UTC) == ("sunday", t(23))

    def test_if_kolkata_late_utc_returns_next_day_at_half_past(self):
        assert slot_in_zone("monday", t(23), KOLKATA) == ("tuesday", t(4, 30))

    def test_if_kathmandu_sunday_evening_utc_returns_monday_quarter_to(self):
        # +5:45, and the week wraps from Sunday to Monday.
        assert slot_in_zone("sunday", t(20), KATHMANDU) == ("monday", t(1, 45))

    def test_if_kathmandu_midday_utc_returns_same_day_quarter_to(self):
        assert slot_in_zone("wednesday", t(10), KATHMANDU) == (
            "wednesday",
            t(15, 45),
        )

    def test_if_adelaide_in_winter_returns_shifted_by_nine_and_a_half(self):
        assert slot_in_zone("monday", t(15), ADELAIDE, ADELAIDE_WINTER) == (
            "tuesday",
            t(0, 30),
        )

    def test_if_adelaide_in_summer_returns_shifted_by_ten_and_a_half(self):
        assert slot_in_zone("monday", t(14), ADELAIDE, ADELAIDE_SUMMER) == (
            "tuesday",
            t(0, 30),
        )

    def test_if_adelaide_in_summer_sunday_returns_monday(self):
        assert slot_in_zone("sunday", t(14), ADELAIDE, ADELAIDE_SUMMER) == (
            "monday",
            t(0, 30),
        )

    def test_if_adelaide_season_changes_same_utc_slot_reads_an_hour_apart(self):
        winter = slot_in_zone("monday", t(15), ADELAIDE, ADELAIDE_WINTER)
        summer = slot_in_zone("monday", t(15), ADELAIDE, ADELAIDE_SUMMER)

        assert winter == ("tuesday", t(0, 30))
        assert summer == ("tuesday", t(1, 30))

    def test_if_time_has_seconds_returns_them_unchanged(self):
        day, time = slot_in_zone("monday", datetime.time(21, 0, 30), KARACHI)

        assert (day, time) == ("tuesday", datetime.time(2, 0, 30))


class TestSlotToUtc:
    def test_if_karachi_early_morning_returns_previous_day_in_utc(self):
        assert slot_to_utc("monday", t(3), KARACHI) == ("sunday", t(22))

    def test_if_karachi_afternoon_returns_same_day_in_utc(self):
        assert slot_to_utc("wednesday", t(15), KARACHI) == ("wednesday", t(10))

    def test_if_last_karachi_hour_before_rollover_returns_previous_day(self):
        assert slot_to_utc("tuesday", t(4), KARACHI) == ("monday", t(23))

    def test_if_first_karachi_hour_after_rollover_returns_same_day_midnight(self):
        assert slot_to_utc("tuesday", t(5), KARACHI) == ("tuesday", t(0))

    def test_if_monday_early_morning_karachi_returns_sunday_in_utc(self):
        # The week wraps backwards: Monday is the first day code.
        assert slot_to_utc("monday", t(2), KARACHI) == ("sunday", t(21))

    def test_if_time_has_minutes_returns_them_converted(self):
        assert slot_to_utc("tuesday", t(2, 30), KARACHI) == ("monday", t(21, 30))

    def test_if_zone_is_utc_returns_the_slot_unchanged(self):
        assert slot_to_utc("monday", t(0), UTC) == ("monday", t(0))

    def test_if_kolkata_early_morning_returns_previous_day_full_hour(self):
        assert slot_to_utc("tuesday", t(4, 30), KOLKATA) == ("monday", t(23))

    def test_if_kathmandu_monday_after_midnight_returns_sunday_in_utc(self):
        # The week wraps backwards, by 5:45.
        assert slot_to_utc("monday", t(0, 45), KATHMANDU) == ("sunday", t(19))

    def test_if_adelaide_in_summer_returns_shifted_back_ten_and_a_half(self):
        assert slot_to_utc("monday", t(0, 30), ADELAIDE, ADELAIDE_SUMMER) == (
            "sunday",
            t(14),
        )


class TestUtcOffsetMinutes:
    @pytest.mark.parametrize(
        "tz, at, minutes",
        [
            (KARACHI, None, 300),
            (KOLKATA, None, 330),
            (KATHMANDU, None, 345),
            (ADELAIDE, ADELAIDE_WINTER, 570),
            (ADELAIDE, ADELAIDE_SUMMER, 630),
        ],
    )
    def test_if_zone_is_given_returns_its_offset_in_minutes(self, tz, at, minutes):
        assert utc_offset_minutes(tz, at) == minutes

    def test_if_no_moment_is_given_returns_the_offset_now(self):
        now = datetime.datetime.now(UTC)

        assert utc_offset_minutes(ADELAIDE) == utc_offset_minutes(ADELAIDE, now)


class TestSlotRoundTrip:
    @pytest.mark.parametrize("tz, at", ZONES)
    @pytest.mark.parametrize("day", DayOfWeek.values)
    @pytest.mark.parametrize("hour", range(24))
    def test_if_converted_there_and_back_returns_the_same_slot(
        self, tz, at, day, hour
    ):
        local = slot_in_zone(day, t(hour), tz, at)

        assert slot_to_utc(*local, tz, at) == (day, t(hour))

    @pytest.mark.parametrize("tz, at", ZONES)
    def test_if_every_utc_slot_is_converted_returns_distinct_local_slots(
        self, tz, at
    ):
        # No two UTC slots may land on the same local slot.
        local_slots = {
            slot_in_zone(day, t(hour), tz, at)
            for day in DayOfWeek.values
            for hour in range(24)
        }

        assert len(local_slots) == 7 * 24


@pytest.mark.django_db
class TestWithWeekMinute:
    @pytest.mark.parametrize(
        "day, hour, tz, at, week_minute",
        [
            # Monday 01:45 in Kathmandu.
            ("sunday", 20, KATHMANDU, None, 105),
            # Tuesday 04:30 in Kolkata.
            ("monday", 23, KOLKATA, None, 1710),
            # Monday 00:30 in Adelaide under daylight saving.
            ("sunday", 14, ADELAIDE, ADELAIDE_SUMMER, 30),
        ],
    )
    def test_if_zone_has_a_partial_hour_offset_returns_its_minute_of_week(
        self, day, hour, tz, at, week_minute
    ):
        baker.make(WeeklyClass, day=day, time=t(hour), duration=60)

        annotated = WeeklyClass.objects.with_week_minute(tz, at).get()

        assert annotated.week_minute == week_minute
