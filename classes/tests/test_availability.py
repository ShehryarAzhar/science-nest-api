import datetime
import itertools
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from model_bakery import baker
from rest_framework import status

from classes.models import Level, Student, Subject, TrialLesson, WeeklyClass
from classes.timeslots import DayOfWeek

SLUG_COUNTER = itertools.count(1)
TOP_KEYS = {"weekly_classes", "trial_lessons"}
WEEKLY_ITEM_KEYS = {"day", "time", "mine"}
TRIAL_ITEM_KEYS = {"starts_at", "day", "time", "mine"}
CLASH_MESSAGE = "This timeslot is already booked."


def make_subject(levels=("o_level",), **kwargs):
    defaults = {
        "slug": f"availability-subject-{next(SLUG_COUNTER)}",
        "price_40_min": Decimal("10.00"),
        "price_60_min": Decimal("15.00"),
    }
    defaults.update(kwargs)
    subject = baker.make(Subject, **defaults)
    subject.levels.set([Level.objects.get(code=code) for code in levels])
    return subject


def make_student(**user_kwargs):
    user = baker.make(get_user_model(), **user_kwargs)
    student = baker.make(Student, user=user, phone_number="+923001234567")
    return user, student


def make_weekly_class(student, day, hour, subject=None):
    subject = subject or make_subject()
    return baker.make(
        WeeklyClass,
        student=student,
        subject=subject,
        level=subject.levels.first(),
        day=day,
        time=datetime.time(hour),
        duration=60,
    )


def next_utc_slot(weekday, hour):
    """The next future datetime (UTC) on the given weekday (0=Monday) + hour."""
    now = timezone.now()
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate += datetime.timedelta(days=(weekday - candidate.weekday()) % 7)
    if candidate <= now:
        candidate += datetime.timedelta(days=7)
    return candidate


def make_lesson(student, starts_at, completed=False, subject=None):
    subject = subject or make_subject()
    return baker.make(
        TrialLesson,
        student=student,
        subject=subject,
        level=subject.levels.first(),
        starts_at=starts_at,
        completed=completed,
    )


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def get_availability(api_client):
    def do_get_availability():
        return api_client.get("/availability/")
    return do_get_availability


@pytest.mark.django_db
class TestRetrieveAvailability:
    def test_if_user_is_anonymous_returns_401(self, get_availability):
        response = get_availability()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_if_user_has_no_student_returns_403(
        self, get_availability, authenticate
    ):
        authenticate(baker.make(get_user_model()))

        response = get_availability()

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_if_user_is_superuser_without_student_returns_403(
        self, get_availability, authenticate
    ):
        authenticate(baker.make(get_user_model(), is_superuser=True, is_staff=True))

        response = get_availability()

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_if_there_are_no_bookings_returns_empty_lists(
        self, get_availability, authenticate
    ):
        user, _ = make_student()
        authenticate(user)

        response = get_availability()

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"weekly_classes": [], "trial_lessons": []}

    def test_if_there_are_bookings_returns_exactly_two_top_level_keys(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        make_weekly_class(student, "monday", 2)
        authenticate(user)

        response = get_availability()

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) == TOP_KEYS

    def test_if_weekly_class_exists_returns_item_with_exact_keys_in_utc(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        make_weekly_class(student, "tuesday", 14)
        authenticate(user)

        response = get_availability()

        assert response.json()["weekly_classes"] == [
            {"day": "tuesday", "time": "14:00:00", "mine": True}
        ]
        assert set(response.data["weekly_classes"][0].keys()) == WEEKLY_ITEM_KEYS

    def test_if_trial_lesson_exists_returns_item_with_exact_keys_in_utc(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        starts_at = next_utc_slot(2, 16)
        make_lesson(student, starts_at)
        authenticate(user)

        response = get_availability()

        assert response.json()["trial_lessons"] == [
            {
                "starts_at": iso(starts_at),
                "day": "wednesday",
                "time": "16:00:00",
                "mine": True,
            }
        ]
        assert set(response.data["trial_lessons"][0].keys()) == TRIAL_ITEM_KEYS

    def test_if_trial_lesson_weekday_differs_in_karachi_returns_utc_day_and_time(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        # Monday 21:00 UTC is Tuesday 02:00 in Asia/Karachi.
        starts_at = next_utc_slot(0, 21)
        make_lesson(student, starts_at)
        authenticate(user)

        response = get_availability()

        item = response.json()["trial_lessons"][0]
        assert item["day"] == "monday"
        assert item["time"] == "21:00:00"
        assert item["starts_at"] == iso(starts_at)

    def test_if_other_students_have_bookings_returns_them_with_mine_false(
        self, get_availability, authenticate
    ):
        user, _ = make_student()
        _, other = make_student()
        make_weekly_class(other, "friday", 10)
        starts_at = next_utc_slot(1, 9)
        make_lesson(other, starts_at)
        authenticate(user)

        response = get_availability()

        assert response.json() == {
            "weekly_classes": [
                {"day": "friday", "time": "10:00:00", "mine": False}
            ],
            "trial_lessons": [
                {
                    "starts_at": iso(starts_at),
                    "day": "tuesday",
                    "time": "09:00:00",
                    "mine": False,
                }
            ],
        }

    def test_if_bookings_are_own_and_others_marks_mine_per_booking(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        _, other = make_student()
        make_weekly_class(student, "monday", 2)
        make_weekly_class(other, "tuesday", 14)
        own_lesson_at = next_utc_slot(2, 16)
        make_lesson(student, own_lesson_at)
        authenticate(user)

        response = get_availability()

        data = response.json()
        assert data["weekly_classes"] == [
            {"day": "monday", "time": "02:00:00", "mine": True},
            {"day": "tuesday", "time": "14:00:00", "mine": False},
        ]
        assert [item["mine"] for item in data["trial_lessons"]] == [True]

    def test_if_same_booking_is_read_by_another_student_returns_mine_false(
        self, get_availability, api_client
    ):
        owner, owner_student = make_student()
        viewer, _ = make_student()
        make_weekly_class(owner_student, "monday", 2)
        make_lesson(owner_student, next_utc_slot(3, 11))

        api_client.force_authenticate(user=owner)
        owner_data = get_availability().json()
        api_client.force_authenticate(user=viewer)
        viewer_data = get_availability().json()

        assert owner_data["weekly_classes"][0]["mine"] is True
        assert owner_data["trial_lessons"][0]["mine"] is True
        assert viewer_data["weekly_classes"][0]["mine"] is False
        assert viewer_data["trial_lessons"][0]["mine"] is False

    def test_if_other_student_has_bookings_returns_no_student_data(
        self, get_availability, authenticate
    ):
        user, _ = make_student()
        other_user, other = make_student(
            username="secretstudentname", email="secret.student@example.com"
        )
        subject = make_subject(
            name="Uniquely Named Physics", slug="uniquely-named-physics"
        )
        make_weekly_class(other, "friday", 10, subject=subject)
        make_lesson(other, next_utc_slot(1, 9), subject=make_subject(
            name="Another Distinct Chemistry",
            slug="another-distinct-chemistry",
            price_40_min=Decimal("1.00"),
            price_60_min=Decimal("2.00"),
        ))
        authenticate(user)

        response = get_availability()

        body = response.content.decode()
        assert "secretstudentname" not in body
        assert "secret.student@example.com" not in body
        assert "Uniquely Named Physics" not in body
        assert "uniquely-named-physics" not in body
        assert "Another Distinct Chemistry" not in body
        for key in (
            "id", "student", "user", "subject", "level", "duration",
            "completed", "price", "username", "email", "day_display",
        ):
            assert f'"{key}"' not in body
        for item in response.data["weekly_classes"]:
            assert set(item.keys()) == WEEKLY_ITEM_KEYS
        for item in response.data["trial_lessons"]:
            assert set(item.keys()) == TRIAL_ITEM_KEYS

    def test_if_trial_lesson_start_has_passed_it_is_not_listed(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        _, other = make_student()
        past = timezone.now().replace(minute=0, second=0, microsecond=0)
        make_lesson(student, past - datetime.timedelta(days=2))
        make_lesson(other, past - datetime.timedelta(days=1))
        authenticate(user)

        response = get_availability()

        assert response.status_code == status.HTTP_200_OK
        assert response.data["trial_lessons"] == []

    def test_if_completed_trial_lesson_is_still_ahead_it_is_listed(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        starts_at = next_utc_slot(4, 12)
        make_lesson(student, starts_at, completed=True)
        authenticate(user)

        response = get_availability()

        assert response.json()["trial_lessons"] == [
            {
                "starts_at": iso(starts_at),
                "day": "friday",
                "time": "12:00:00",
                "mine": True,
            }
        ]

    def test_if_weekly_classes_are_created_unordered_returns_week_order(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        _, other = make_student()
        make_weekly_class(student, "sunday", 9)
        make_weekly_class(other, "wednesday", 15)
        make_weekly_class(student, "monday", 18)
        make_weekly_class(other, "wednesday", 8)
        make_weekly_class(student, "monday", 3)
        authenticate(user)

        response = get_availability()

        assert [
            (item["day"], item["time"])
            for item in response.json()["weekly_classes"]
        ] == [
            ("monday", "03:00:00"),
            ("monday", "18:00:00"),
            ("wednesday", "08:00:00"),
            ("wednesday", "15:00:00"),
            ("sunday", "09:00:00"),
        ]

    def test_if_trial_lessons_are_created_unordered_returns_earliest_first(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        _, other_a = make_student()
        _, other_b = make_student()
        late = next_utc_slot(0, 20) + datetime.timedelta(days=14)
        middle = next_utc_slot(3, 10) + datetime.timedelta(days=7)
        early = next_utc_slot(5, 7)
        make_lesson(student, late)
        make_lesson(other_a, early)
        make_lesson(other_b, middle)
        authenticate(user)

        response = get_availability()

        assert [
            item["starts_at"] for item in response.json()["trial_lessons"]
        ] == [iso(early), iso(middle), iso(late)]

    def test_if_weekly_class_is_booked_moved_and_deleted_next_get_reflects_it(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        authenticate(user)
        assert get_availability().data["weekly_classes"] == []

        weekly_class = make_weekly_class(student, "monday", 2)
        booked = get_availability().json()["weekly_classes"]

        weekly_class.day = "thursday"
        weekly_class.time = datetime.time(7)
        weekly_class.save()
        moved = get_availability().json()["weekly_classes"]

        weekly_class.delete()
        deleted = get_availability().json()["weekly_classes"]

        assert booked == [{"day": "monday", "time": "02:00:00", "mine": True}]
        assert moved == [{"day": "thursday", "time": "07:00:00", "mine": True}]
        assert deleted == []

    def test_if_trial_lesson_is_booked_and_deleted_next_get_reflects_it(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        authenticate(user)
        assert get_availability().data["trial_lessons"] == []

        lesson = make_lesson(student, next_utc_slot(2, 16))
        booked = get_availability().json()["trial_lessons"]
        lesson.delete()
        deleted = get_availability().json()["trial_lessons"]

        assert len(booked) == 1
        assert deleted == []

    def test_if_bookings_grow_query_count_stays_the_same(
        self, get_availability, authenticate
    ):
        user, student = make_student()
        make_weekly_class(student, "monday", 2)
        make_lesson(student, next_utc_slot(2, 16))
        authenticate(user)
        with CaptureQueriesContext(connection) as one_booking:
            get_availability()

        days = ["tuesday", "wednesday", "thursday", "friday", "saturday"]
        for index, day in enumerate(days):
            _, other = make_student()
            make_weekly_class(other, day, 5 + index)
            make_lesson(other, next_utc_slot(index, 10) + datetime.timedelta(days=7))
        with CaptureQueriesContext(connection) as many_bookings:
            response = get_availability()

        assert len(response.data["weekly_classes"]) == 6
        assert len(response.data["trial_lessons"]) == 6
        assert len(many_bookings) == len(one_booking)


@pytest.mark.django_db
class TestWriteAvailability:
    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_if_method_is_not_get_returns_405_and_changes_nothing(
        self, api_client, authenticate, method
    ):
        user, student = make_student()
        make_weekly_class(student, "monday", 2)
        make_lesson(student, next_utc_slot(2, 16))
        authenticate(user)

        response = getattr(api_client, method)("/availability/", {})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert WeeklyClass.objects.count() == 1
        assert TrialLesson.objects.count() == 1


@pytest.mark.django_db
class TestBookingRoutesStillRejectListedSlots:
    def test_if_weekly_class_slot_is_listed_as_taken_post_classes_returns_400(
        self, api_client, authenticate, get_availability
    ):
        user, _ = make_student()
        _, other = make_student()
        make_weekly_class(other, "tuesday", 14)
        subject = make_subject()
        authenticate(user)
        listed = get_availability().json()["weekly_classes"]

        response = api_client.post(
            "/classes/",
            {
                "subject": subject.id,
                "level": "o_level",
                "day": listed[0]["day"],
                "time": listed[0]["time"],
                "duration": 60,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CLASH_MESSAGE in str(response.data)

    def test_if_trial_lesson_blocks_weekly_slot_post_classes_returns_400(
        self, api_client, authenticate, get_availability
    ):
        user, _ = make_student()
        _, other = make_student()
        make_lesson(other, next_utc_slot(2, 16))
        subject = make_subject()
        authenticate(user)
        listed = get_availability().json()["trial_lessons"]

        response = api_client.post(
            "/classes/",
            {
                "subject": subject.id,
                "level": "o_level",
                "day": listed[0]["day"],
                "time": listed[0]["time"],
                "duration": 60,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CLASH_MESSAGE in str(response.data)

    def test_if_weekly_class_slot_is_listed_as_taken_post_trial_lessons_returns_400(
        self, api_client, authenticate, get_availability
    ):
        user, _ = make_student()
        _, other = make_student()
        make_weekly_class(other, "wednesday", 16)
        subject = make_subject()
        authenticate(user)
        assert get_availability().json()["weekly_classes"][0]["mine"] is False

        response = api_client.post(
            "/trial-lessons/",
            {
                "subject": subject.id,
                "level": "o_level",
                "starts_at": iso(next_utc_slot(2, 16)),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CLASH_MESSAGE in str(response.data["starts_at"])

    def test_if_trial_lesson_time_is_listed_as_taken_post_trial_lessons_returns_400(
        self, api_client, authenticate, get_availability
    ):
        user, _ = make_student()
        _, other = make_student()
        starts_at = next_utc_slot(4, 12)
        make_lesson(other, starts_at)
        subject = make_subject()
        authenticate(user)
        listed = get_availability().json()["trial_lessons"]

        response = api_client.post(
            "/trial-lessons/",
            {
                "subject": subject.id,
                "level": "o_level",
                "starts_at": listed[0]["starts_at"],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CLASH_MESSAGE in str(response.data["starts_at"])
