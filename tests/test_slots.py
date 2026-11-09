"""Unit-тесты чистых правил построения слотов (без базы данных)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import pairwise

import pytest

from barberbot.booking.slots import (
    MOSCOW,
    SLOT_STEP,
    Interval,
    SlotIssue,
    day_window,
    first_candidate,
    generate_slots,
    start_issue,
)

MONDAY = date(2030, 1, 7)
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=MOSCOW)
DURATION = timedelta(minutes=60)


def monday_window() -> Interval:
    return day_window(MONDAY, time(9, 0), time(17, 0))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 7, hour, minute, tzinfo=MOSCOW)


def test_fixed_monday_is_monday() -> None:
    assert NOW.weekday() == 0
    assert NOW.date() == MONDAY


@pytest.mark.parametrize(
    ("window_start", "expected"),
    [
        (at(9, 0), at(9, 0)),
        (at(9, 10), at(9, 30)),
        (at(9, 29), at(9, 30)),
        (at(9, 30), at(9, 30)),
        (at(9, 31), at(10, 0)),
    ],
)
def test_first_candidate_aligns_to_step(
    window_start: datetime, expected: datetime
) -> None:
    assert first_candidate(window_start, step=SLOT_STEP) == expected


def test_generate_slots_uses_thirty_minute_step() -> None:
    slots = generate_slots(window=monday_window(), duration=DURATION, now=NOW)

    assert len(slots) == 15
    assert slots[0] == at(9, 0)
    assert slots[-1] == at(16, 0)
    assert all(right - left == SLOT_STEP for left, right in pairwise(slots))


def test_service_must_fit_fully_inside_working_hours() -> None:
    slots = generate_slots(window=monday_window(), duration=DURATION, now=NOW)
    assert at(16, 30) not in slots


@pytest.mark.parametrize(
    ("duration_minutes", "expected_last", "expected_count"),
    [
        (30, at(16, 30), 16),
        (45, at(16, 0), 15),
        (60, at(16, 0), 15),
    ],
)
def test_service_duration_changes_available_starts(
    duration_minutes: int, expected_last: datetime, expected_count: int
) -> None:
    slots = generate_slots(
        window=monday_window(),
        duration=timedelta(minutes=duration_minutes),
        now=NOW,
    )

    assert slots[-1] == expected_last
    assert len(slots) == expected_count
    assert all(
        slot + timedelta(minutes=duration_minutes) <= monday_window().end
        for slot in slots
    )


def test_busy_interval_blocks_overlapping_slots_only() -> None:
    busy = [Interval(at(10, 0), at(11, 0))]

    slots = generate_slots(
        window=monday_window(), duration=DURATION, now=NOW, busy=busy
    )

    assert at(9, 0) in slots  # 09:00-10:00 заканчивается ровно к началу занятости
    assert at(9, 30) not in slots
    assert at(10, 0) not in slots
    assert at(10, 30) not in slots
    assert at(11, 0) in slots


def test_adjacent_bookings_do_not_intersect() -> None:
    busy = [Interval(at(10, 0), at(11, 0))]

    slots = generate_slots(
        window=monday_window(), duration=DURATION, now=NOW, busy=busy
    )

    occupied = busy[0]
    for slot in slots:
        assert not occupied.overlaps(slot, slot + DURATION)


def test_past_slots_are_not_offered() -> None:
    now = at(12, 0)

    slots = generate_slots(window=monday_window(), duration=DURATION, now=now)

    assert slots[0] == at(12, 30)
    assert all(slot > now for slot in slots)


def test_no_slots_when_every_start_is_in_the_past() -> None:
    now = at(17, 0)

    assert generate_slots(window=monday_window(), duration=DURATION, now=now) == []


def test_no_slots_when_service_longer_than_working_day() -> None:
    short_window = day_window(MONDAY, time(9, 0), time(10, 0))

    slots = generate_slots(window=short_window, duration=timedelta(minutes=90), now=NOW)

    assert slots == []


@pytest.mark.parametrize(
    ("starts_at", "expected"),
    [
        (at(8, 30), SlotIssue.OUTSIDE_WORKING_HOURS),
        (at(9, 0), None),
        (at(9, 10), SlotIssue.OFF_GRID),
        (at(16, 30), SlotIssue.DOES_NOT_FIT),
        (at(17, 0), SlotIssue.OUTSIDE_WORKING_HOURS),
        (at(18, 0), SlotIssue.OUTSIDE_WORKING_HOURS),
    ],
)
def test_start_issue_classifies_invalid_times(
    starts_at: datetime, expected: SlotIssue | None
) -> None:
    assert (
        start_issue(
            starts_at=starts_at,
            window=monday_window(),
            duration=DURATION,
            now=NOW,
        )
        is expected
    )


def test_start_issue_reports_past_before_other_reasons() -> None:
    issue = start_issue(
        starts_at=at(7, 0),
        window=monday_window(),
        duration=DURATION,
        now=at(8, 0),
    )

    assert issue is SlotIssue.PAST
