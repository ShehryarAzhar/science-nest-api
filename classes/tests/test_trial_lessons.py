import datetime
import itertools
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone
from model_bakery import baker
from rest_framework import status

from classes.admin import SubjectAdminForm
from classes.models import Level, Student, Subject, TrialLesson, WeeklyClass
from classes.timeslots import DayOfWeek

SLUG_COUNTER = itertools.count(1)
SUBJECT_KEYS = {"id", "name", "slug", "levels"}
LEVEL_KEYS = {"code", "name"}
LESSON_KEYS = {"id", "subject", "level", "starts_at", "completed"}
CLASH_MESSAGE = "This timeslot is already booked."
ALREADY_BOOKED_MESSAGE = "You have already booked a trial lesson."
LOCKED_MESSAGE = "This trial lesson can no longer be changed."
PAST_MESSAGE = "A trial lesson cannot be booked in the past."


def get_level(code):
    return Level.objects.get(code=code)


def make_subject(levels=("o_level",), **kwargs):
    defaults = {
        "slug": f"subject-{next(SLUG_COUNTER)}",
        "price_40_min": Decimal("10.00"),
        "price_60_min": Decimal("15.00"),
    }
    defaults.update(kwargs)
    subject = baker.make(Subject, **defaults)
    subject.levels.set([get_level(code) for code in levels])
    return subject


def make_student():
    user = baker.make(get_user_model())
    student = baker.make(Student, user=user, phone_number="+923001234567")
    return user, student


def future_hour(days=3, hours=0):
    """A full UTC hour in the future."""
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    return now + datetime.timedelta(days=days, hours=hours)


def past_hour(days=2):
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    return now - datetime.timedelta(days=days)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_lesson(student, starts_at=None, subject=None, level=None, completed=False):
    subject = subject or make_subject()
    return baker.make(
        TrialLesson,
        student=student,
        subject=subject,
        level=level or subject.levels.first(),
        starts_at=starts_at or future_hour(),
        completed=completed,
    )


def make_weekly_class(student, starts_at, duration=60, subject=None):
    subject = subject or make_subject()
    return baker.make(
        WeeklyClass,
        student=student,
        subject=subject,
        level=subject.levels.first(),
        day=DayOfWeek.values[starts_at.weekday()],
        time=starts_at.time(),
        duration=duration,
    )


def payload(subject, /, starts_at=None, **overrides):
    data = {
        "subject": subject.id,
        "level": subject.levels.first().code,
        "starts_at": iso(starts_at or future_hour()),
    }
    data.update(overrides)
    return data


def class_payload(subject, starts_at, **overrides):
    data = {
        "subject": subject.id,
        "level": subject.levels.first().code,
        "day": DayOfWeek.values[starts_at.weekday()],
        "time": starts_at.strftime("%H:00"),
        "duration": 60,
    }
    data.update(overrides)
    return data


@pytest.fixture
def student_user(authenticate):
    user, student = make_student()
    authenticate(user)
    return user, student


@pytest.fixture
def list_lessons(api_client):
    def do_list():
        return api_client.get("/trial-lessons/")

    return do_list


@pytest.fixture
def create_lesson(api_client):
    def do_create(data):
        return api_client.post("/trial-lessons/", data, format="json")

    return do_create


@pytest.fixture
def retrieve_lesson(api_client):
    def do_retrieve(lesson_id):
        return api_client.get(f"/trial-lessons/{lesson_id}/")

    return do_retrieve


@pytest.fixture
def update_lesson(api_client):
    def do_update(lesson_id, data):
        return api_client.put(f"/trial-lessons/{lesson_id}/", data, format="json")

    return do_update


@pytest.fixture
def patch_lesson(api_client):
    def do_patch(lesson_id, data):
        return api_client.patch(f"/trial-lessons/{lesson_id}/", data, format="json")

    return do_patch


@pytest.fixture
def delete_lesson(api_client):
    def do_delete(lesson_id):
        return api_client.delete(f"/trial-lessons/{lesson_id}/")

    return do_delete


@pytest.fixture
def create_class(api_client):
    def do_create(data):
        return api_client.post("/classes/", data, format="json")

    return do_create


ROUTES = [
    ("get", "/trial-lessons/"),
    ("post", "/trial-lessons/"),
    ("get", "/trial-lessons/1/"),
    ("put", "/trial-lessons/1/"),
    ("patch", "/trial-lessons/1/"),
    ("delete", "/trial-lessons/1/"),
]


@pytest.mark.django_db
class TestAccess:
    @pytest.mark.parametrize("method, url", ROUTES)
    def test_if_user_is_anonymous_returns_401(self, api_client, method, url):
        response = getattr(api_client, method)(url, {}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize("method, url", ROUTES)
    def test_if_user_has_no_student_returns_403(
        self, api_client, authenticate, method, url
    ):
        authenticate(baker.make(get_user_model()))

        response = getattr(api_client, method)(url, {}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_if_user_is_superuser_without_student_returns_403(
        self, api_client, list_lessons
    ):
        superuser = baker.make(get_user_model(), is_superuser=True, is_staff=True)
        api_client.force_authenticate(user=superuser)

        response = list_lessons()

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCreateTrialLesson:
    def test_if_data_is_valid_returns_201(self, create_lesson, student_user):
        _, student = student_user
        subject = make_subject(levels=("o_level", "a_level"))
        starts_at = future_hour()

        response = create_lesson(
            payload(subject, starts_at, level="a_level")
        )

        assert response.status_code == status.HTTP_201_CREATED
        lesson = TrialLesson.objects.get()
        assert response.json() == {
            "id": lesson.id,
            "subject": {
                "id": subject.id,
                "name": subject.name,
                "slug": subject.slug,
                "levels": [
                    {"code": level.code, "name": level.name}
                    for level in subject.levels.all()
                ],
            },
            "level": {
                "code": "a_level",
                "name": get_level("a_level").name,
            },
            "starts_at": iso(starts_at),
            "completed": False,
        }
        assert lesson.student == student
        assert lesson.subject == subject
        assert lesson.level == get_level("a_level")
        assert lesson.starts_at == starts_at
        assert lesson.completed is False

    def test_if_data_is_valid_response_has_exact_keys(
        self, create_lesson, student_user
    ):
        subject = make_subject()

        response = create_lesson(payload(subject))

        body = response.json()
        assert set(body) == LESSON_KEYS
        assert set(body["subject"]) == SUBJECT_KEYS
        assert "price_40_min" not in body["subject"]
        assert "price_60_min" not in body["subject"]
        assert "description" not in body["subject"]
        assert set(body["level"]) == LEVEL_KEYS

    def test_if_body_has_student_or_user_they_are_ignored(
        self, create_lesson, student_user
    ):
        _, student = student_user
        other_user, other_student = make_student()
        subject = make_subject()

        response = create_lesson(
            payload(subject, student=other_student.id, user=other_user.id)
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert TrialLesson.objects.get().student == student
        assert not TrialLesson.objects.filter(student=other_student).exists()

    def test_if_body_has_completed_true_it_is_ignored(
        self, create_lesson, student_user
    ):
        subject = make_subject()

        response = create_lesson(payload(subject, completed=True))

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["completed"] is False
        assert TrialLesson.objects.get().completed is False

    def test_if_starts_at_has_offset_it_is_stored_as_same_moment_in_utc(
        self, create_lesson, student_user
    ):
        subject = make_subject()
        starts_at = future_hour()
        offset = datetime.timezone(datetime.timedelta(hours=5))
        local = starts_at.astimezone(offset).isoformat()

        response = create_lesson(
            {"subject": subject.id, "level": "o_level", "starts_at": local}
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["starts_at"] == iso(starts_at)
        assert TrialLesson.objects.get().starts_at == starts_at

    @pytest.mark.parametrize(
        "offset", [{"hours": 5, "minutes": 30}, {"hours": 5, "minutes": 45}]
    )
    def test_if_offset_is_not_whole_hours_and_utc_is_full_hour_returns_201(
        self, create_lesson, student_user, offset
    ):
        # Asia/Kolkata and Asia/Kathmandu: the lesson reads at :30 or :45
        # locally, which is fine as long as it is a full hour in UTC.
        subject = make_subject()
        starts_at = future_hour()
        zone = datetime.timezone(datetime.timedelta(**offset))
        local = starts_at.astimezone(zone).isoformat()

        response = create_lesson(
            {"subject": subject.id, "level": "o_level", "starts_at": local}
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["starts_at"] == iso(starts_at)
        assert TrialLesson.objects.get().starts_at == starts_at

    @pytest.mark.parametrize(
        "offset", [{"hours": 5, "minutes": 30}, {"hours": 5, "minutes": 45}]
    )
    def test_if_local_full_hour_is_not_full_hour_in_utc_returns_400(
        self, create_lesson, student_user, offset
    ):
        # 08:00 at +5:30 is 02:30 UTC: the full-hour rule is judged in UTC.
        subject = make_subject()
        zone = datetime.timezone(datetime.timedelta(**offset))
        local = future_hour().astimezone(zone).replace(minute=0).isoformat()

        response = create_lesson(
            {"subject": subject.id, "level": "o_level", "starts_at": local}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data
        assert not TrialLesson.objects.exists()

    @pytest.mark.parametrize("missing", ["subject", "level", "starts_at"])
    def test_if_field_is_missing_returns_400(
        self, create_lesson, student_user, missing
    ):
        data = payload(make_subject())
        del data[missing]

        response = create_lesson(data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert missing in response.data
        assert not TrialLesson.objects.exists()

    def test_if_subject_does_not_exist_returns_400(
        self, create_lesson, student_user
    ):
        response = create_lesson(payload(make_subject(), subject=999999))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "subject" in response.data
        assert not TrialLesson.objects.exists()

    def test_if_level_code_does_not_exist_returns_400(
        self, create_lesson, student_user
    ):
        response = create_lesson(payload(make_subject(), level="no_such_level"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "level" in response.data
        assert not TrialLesson.objects.exists()

    def test_if_starts_at_is_malformed_returns_400(
        self, create_lesson, student_user
    ):
        data = payload(make_subject())
        data["starts_at"] = "not-a-date"

        response = create_lesson(data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data
        assert not TrialLesson.objects.exists()

    def test_if_level_is_one_of_subject_levels_returns_201(
        self, create_lesson, student_user
    ):
        subject = make_subject(levels=("o_level", "university"))

        response = create_lesson(payload(subject, level="university"))

        assert response.status_code == status.HTTP_201_CREATED

    def test_if_level_is_not_one_of_subject_levels_returns_400(
        self, create_lesson, student_user
    ):
        subject = make_subject(levels=("o_level",))

        response = create_lesson(payload(subject, level="a_level"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "level" in response.data
        assert not TrialLesson.objects.exists()

    def test_if_starts_at_is_on_full_hour_returns_201(
        self, create_lesson, student_user
    ):
        response = create_lesson(payload(make_subject(), future_hour()))

        assert response.status_code == status.HTTP_201_CREATED

    @pytest.mark.parametrize(
        "change", [{"minute": 30}, {"minute": 15}, {"second": 30}]
    )
    def test_if_starts_at_is_not_on_full_hour_returns_400(
        self, create_lesson, student_user, change
    ):
        starts_at = future_hour().replace(**change)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data
        assert not TrialLesson.objects.exists()

    def test_if_starts_at_is_in_the_past_returns_400(
        self, create_lesson, student_user
    ):
        response = create_lesson(payload(make_subject(), past_hour()))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data
        assert not TrialLesson.objects.exists()

    @pytest.mark.parametrize("kind", ["open", "completed", "passed"])
    def test_if_student_already_has_trial_lesson_returns_400(
        self, create_lesson, student_user, kind
    ):
        _, student = student_user
        if kind == "open":
            make_lesson(student, future_hour(days=5))
        elif kind == "completed":
            make_lesson(student, future_hour(days=5), completed=True)
        else:
            make_lesson(student, past_hour())
        subject = make_subject()

        response = create_lesson(payload(subject, future_hour(days=6)))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [ALREADY_BOOKED_MESSAGE]
        assert TrialLesson.objects.count() == 1

    def test_if_other_student_has_trial_lesson_returns_201(
        self, create_lesson, student_user
    ):
        _, other_student = make_student()
        make_lesson(other_student, future_hour(days=5))

        response = create_lesson(payload(make_subject(), future_hour(days=6)))

        assert response.status_code == status.HTTP_201_CREATED
        assert TrialLesson.objects.count() == 2

    def test_if_timeslot_is_taken_by_other_student_returns_400(
        self, create_lesson, student_user
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_lesson(other_student, starts_at)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["starts_at"] == [CLASH_MESSAGE]
        assert TrialLesson.objects.count() == 1

    @pytest.mark.parametrize("offset", [{"hours": 1}, {"days": 1}])
    def test_if_other_trial_lesson_is_at_different_time_returns_201(
        self, create_lesson, student_user, offset
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_lesson(other_student, starts_at)

        response = create_lesson(
            payload(make_subject(), starts_at + datetime.timedelta(**offset))
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_if_weekly_class_of_other_student_holds_slot_returns_400(
        self, create_lesson, student_user
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_weekly_class(other_student, starts_at)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["starts_at"] == [CLASH_MESSAGE]
        assert not TrialLesson.objects.exists()

    def test_if_weekly_class_of_same_student_holds_slot_returns_400(
        self, create_lesson, student_user
    ):
        _, student = student_user
        starts_at = future_hour()
        make_weekly_class(student, starts_at)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data

    def test_if_weekly_class_is_40_minutes_it_still_blocks(
        self, create_lesson, student_user
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_weekly_class(other_student, starts_at, duration=40)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data

    def test_if_weekly_class_is_on_same_weekday_in_a_later_week_it_blocks(
        self, create_lesson, student_user
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_weekly_class(other_student, starts_at)

        response = create_lesson(
            payload(make_subject(), starts_at + datetime.timedelta(weeks=1))
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data

    @pytest.mark.parametrize("offset", [{"hours": 1}, {"days": 1}])
    def test_if_weekly_class_is_at_other_hour_or_weekday_returns_201(
        self, create_lesson, student_user, offset
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_weekly_class(other_student, starts_at)

        response = create_lesson(
            payload(make_subject(), starts_at + datetime.timedelta(**offset))
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestListTrialLessons:
    def test_if_student_has_lesson_returns_only_it(
        self, list_lessons, student_user
    ):
        _, student = student_user
        _, other_student = make_student()
        lesson = make_lesson(student, future_hour(days=4))
        make_lesson(other_student, future_hour(days=5))

        response = list_lessons()

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)
        assert [item["id"] for item in response.json()] == [lesson.id]
        assert set(response.json()[0]) == LESSON_KEYS

    def test_if_student_has_no_lesson_returns_empty_list(
        self, list_lessons, student_user
    ):
        _, other_student = make_student()
        make_lesson(other_student)

        response = list_lessons()

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


@pytest.mark.django_db
class TestRetrieveTrialLesson:
    def test_if_lesson_is_own_returns_200(self, retrieve_lesson, student_user):
        _, student = student_user
        subject = make_subject(levels=("o_level", "a_level"))
        starts_at = future_hour()
        lesson = make_lesson(
            student, starts_at, subject=subject, level=get_level("a_level")
        )

        response = retrieve_lesson(lesson.id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": lesson.id,
            "subject": {
                "id": subject.id,
                "name": subject.name,
                "slug": subject.slug,
                "levels": [
                    {"code": level.code, "name": level.name}
                    for level in subject.levels.all()
                ],
            },
            "level": {"code": "a_level", "name": get_level("a_level").name},
            "starts_at": iso(starts_at),
            "completed": False,
        }

    def test_if_lesson_is_completed_returns_200(self, retrieve_lesson, student_user):
        _, student = student_user
        lesson = make_lesson(student, completed=True)

        response = retrieve_lesson(lesson.id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["completed"] is True

    def test_if_lesson_has_passed_returns_200(self, retrieve_lesson, student_user):
        _, student = student_user
        lesson = make_lesson(student, past_hour())

        response = retrieve_lesson(lesson.id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == lesson.id

    def test_if_lesson_belongs_to_other_student_returns_404(
        self, retrieve_lesson, student_user
    ):
        _, other_student = make_student()
        lesson = make_lesson(other_student)

        response = retrieve_lesson(lesson.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_if_id_does_not_exist_returns_404(self, retrieve_lesson, student_user):
        response = retrieve_lesson(999999)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestUpdateTrialLesson:
    def test_if_data_is_valid_put_updates_lesson(self, update_lesson, student_user):
        _, student = student_user
        lesson = make_lesson(student)
        new_subject = make_subject(levels=("a_level", "university"))
        new_starts_at = future_hour(days=6)

        response = update_lesson(
            lesson.id, payload(new_subject, new_starts_at, level="university")
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["starts_at"] == iso(new_starts_at)
        lesson.refresh_from_db()
        assert lesson.subject == new_subject
        assert lesson.level == get_level("university")
        assert lesson.starts_at == new_starts_at

    def test_if_starts_at_is_unchanged_put_succeeds(
        self, update_lesson, student_user
    ):
        _, student = student_user
        starts_at = future_hour()
        lesson = make_lesson(student, starts_at)

        response = update_lesson(lesson.id, payload(lesson.subject, starts_at))

        assert response.status_code == status.HTTP_200_OK

    def test_if_level_is_not_in_subject_put_returns_400(
        self, update_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)

        response = update_lesson(
            lesson.id, payload(lesson.subject, lesson.starts_at, level="university")
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "level" in response.data

    def test_if_starts_at_is_not_full_hour_put_returns_400(
        self, update_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)
        starts_at = future_hour(days=6).replace(minute=30)

        response = update_lesson(lesson.id, payload(lesson.subject, starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data

    def test_if_starts_at_is_past_put_returns_400(self, update_lesson, student_user):
        _, student = student_user
        original = future_hour()
        lesson = make_lesson(student, original)

        response = update_lesson(lesson.id, payload(lesson.subject, past_hour()))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data
        lesson.refresh_from_db()
        assert lesson.starts_at == original

    def test_if_starts_at_is_taken_put_returns_400(self, update_lesson, student_user):
        _, student = student_user
        _, other_student = make_student()
        taken = future_hour(days=6)
        make_lesson(other_student, taken)
        lesson = make_lesson(student)

        response = update_lesson(lesson.id, payload(lesson.subject, taken))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["starts_at"] == [CLASH_MESSAGE]

    def test_if_starts_at_is_on_weekly_class_slot_put_returns_400(
        self, update_lesson, student_user
    ):
        _, student = student_user
        _, other_student = make_student()
        slot = future_hour(days=6)
        make_weekly_class(other_student, slot)
        lesson = make_lesson(student)

        response = update_lesson(lesson.id, payload(lesson.subject, slot))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data

    def test_if_body_has_completed_true_put_ignores_it(
        self, update_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)

        response = update_lesson(
            lesson.id, payload(lesson.subject, lesson.starts_at, completed=True)
        )

        assert response.status_code == status.HTTP_200_OK
        lesson.refresh_from_db()
        assert lesson.completed is False

    def test_if_lesson_belongs_to_other_student_put_returns_404(
        self, update_lesson, student_user
    ):
        _, other_student = make_student()
        original = future_hour()
        lesson = make_lesson(other_student, original)

        response = update_lesson(
            lesson.id, payload(lesson.subject, future_hour(days=6))
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        lesson.refresh_from_db()
        assert lesson.starts_at == original

    def test_if_starts_at_is_changed_patch_updates_lesson(
        self, patch_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)
        new_starts_at = future_hour(days=7)

        response = patch_lesson(lesson.id, {"starts_at": iso(new_starts_at)})

        assert response.status_code == status.HTTP_200_OK
        lesson.refresh_from_db()
        assert lesson.starts_at == new_starts_at

    def test_if_only_level_is_changed_patch_succeeds(
        self, patch_lesson, student_user
    ):
        _, student = student_user
        subject = make_subject(levels=("o_level", "a_level"))
        lesson = make_lesson(student, subject=subject, level=get_level("o_level"))

        response = patch_lesson(lesson.id, {"level": "a_level"})

        assert response.status_code == status.HTTP_200_OK
        lesson.refresh_from_db()
        assert lesson.level == get_level("a_level")

    def test_if_only_level_is_not_in_current_subject_patch_returns_400(
        self, patch_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student, subject=make_subject(levels=("o_level",)))

        response = patch_lesson(lesson.id, {"level": "a_level"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "level" in response.data
        lesson.refresh_from_db()
        assert lesson.level == get_level("o_level")

    def test_if_only_subject_has_current_level_patch_succeeds(
        self, patch_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)
        new_subject = make_subject(levels=("o_level", "a_level"))

        response = patch_lesson(lesson.id, {"subject": new_subject.id})

        assert response.status_code == status.HTTP_200_OK
        lesson.refresh_from_db()
        assert lesson.subject == new_subject

    def test_if_only_subject_lacks_current_level_patch_returns_400(
        self, patch_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)
        new_subject = make_subject(levels=("a_level",))
        old_subject = lesson.subject

        response = patch_lesson(lesson.id, {"subject": new_subject.id})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "level" in response.data
        lesson.refresh_from_db()
        assert lesson.subject == old_subject

    @pytest.mark.parametrize("kind", ["not_full_hour", "past", "taken", "weekly"])
    def test_if_starts_at_is_invalid_patch_returns_400(
        self, patch_lesson, student_user, kind
    ):
        _, student = student_user
        _, other_student = make_student()
        taken = future_hour(days=6)
        lesson = make_lesson(student)
        if kind == "not_full_hour":
            starts_at = future_hour(days=7).replace(minute=30)
        elif kind == "past":
            starts_at = past_hour()
        elif kind == "taken":
            make_lesson(other_student, taken)
            starts_at = taken
        else:
            make_weekly_class(other_student, taken)
            starts_at = taken

        response = patch_lesson(lesson.id, {"starts_at": iso(starts_at)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "starts_at" in response.data

    def test_if_body_has_completed_true_patch_ignores_it(
        self, patch_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)

        response = patch_lesson(lesson.id, {"completed": True})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["completed"] is False
        lesson.refresh_from_db()
        assert lesson.completed is False

    def test_if_lesson_belongs_to_other_student_patch_returns_404(
        self, patch_lesson, student_user
    ):
        _, other_student = make_student()
        original = future_hour()
        lesson = make_lesson(other_student, original)

        response = patch_lesson(
            lesson.id, {"starts_at": iso(future_hour(days=6))}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        lesson.refresh_from_db()
        assert lesson.starts_at == original

    def test_if_locked_lesson_belongs_to_other_student_returns_404(
        self, patch_lesson, student_user
    ):
        _, other_student = make_student()
        lesson = make_lesson(other_student, completed=True)

        response = patch_lesson(lesson.id, {"level": "o_level"})

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestLockedTrialLesson:
    @staticmethod
    def make_locked(student, kind):
        if kind == "completed":
            return make_lesson(student, future_hour(), completed=True)
        return make_lesson(student, past_hour())

    @pytest.mark.parametrize("kind", ["completed", "passed"])
    def test_if_lesson_is_locked_put_returns_403(
        self, update_lesson, student_user, kind
    ):
        _, student = student_user
        lesson = self.make_locked(student, kind)
        original = lesson.starts_at

        response = update_lesson(
            lesson.id, payload(lesson.subject, future_hour(days=8))
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["detail"] == LOCKED_MESSAGE
        lesson.refresh_from_db()
        assert lesson.starts_at == original

    @pytest.mark.parametrize("kind", ["completed", "passed"])
    def test_if_lesson_is_locked_patch_returns_403(
        self, patch_lesson, student_user, kind
    ):
        _, student = student_user
        lesson = self.make_locked(student, kind)
        original = lesson.starts_at

        response = patch_lesson(lesson.id, {"starts_at": iso(future_hour(days=8))})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["detail"] == LOCKED_MESSAGE
        lesson.refresh_from_db()
        assert lesson.starts_at == original

    @pytest.mark.parametrize("kind", ["completed", "passed"])
    def test_if_lesson_is_locked_delete_returns_403(
        self, delete_lesson, student_user, kind
    ):
        _, student = student_user
        lesson = self.make_locked(student, kind)

        response = delete_lesson(lesson.id)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["detail"] == LOCKED_MESSAGE
        assert TrialLesson.objects.filter(id=lesson.id).exists()

    @pytest.mark.parametrize("kind", ["completed", "passed"])
    def test_if_lesson_is_locked_and_body_is_invalid_put_returns_403(
        self, update_lesson, student_user, kind
    ):
        _, student = student_user
        lesson = self.make_locked(student, kind)

        response = update_lesson(lesson.id, {"starts_at": "garbage"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["detail"] == LOCKED_MESSAGE

    @pytest.mark.parametrize("kind", ["completed", "passed"])
    def test_if_lesson_is_locked_and_body_is_invalid_patch_returns_403(
        self, patch_lesson, student_user, kind
    ):
        _, student = student_user
        lesson = self.make_locked(student, kind)

        response = patch_lesson(lesson.id, {"level": "no_such_level"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["detail"] == LOCKED_MESSAGE

    @pytest.mark.parametrize("kind", ["completed", "passed"])
    def test_if_lesson_is_locked_student_still_cannot_book_another(
        self, create_lesson, student_user, kind
    ):
        _, student = student_user
        self.make_locked(student, kind)

        response = create_lesson(payload(make_subject(), future_hour(days=9)))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [ALREADY_BOOKED_MESSAGE]


@pytest.mark.django_db
class TestDeleteTrialLesson:
    def test_if_lesson_is_open_returns_204(self, delete_lesson, student_user):
        _, student = student_user
        lesson = make_lesson(student)

        response = delete_lesson(lesson.id)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TrialLesson.objects.filter(id=lesson.id).exists()

    def test_if_lesson_is_deleted_student_can_book_again(
        self, delete_lesson, create_lesson, student_user
    ):
        _, student = student_user
        lesson = make_lesson(student)
        delete_lesson(lesson.id)

        response = create_lesson(payload(make_subject(), future_hour(days=6)))

        assert response.status_code == status.HTTP_201_CREATED
        assert TrialLesson.objects.filter(student=student).count() == 1

    def test_if_lesson_is_deleted_its_time_can_be_booked_by_other_student(
        self, api_client, delete_lesson, create_lesson, student_user
    ):
        _, student = student_user
        starts_at = future_hour()
        lesson = make_lesson(student, starts_at)
        delete_lesson(lesson.id)
        other_user, other_student = make_student()
        api_client.force_authenticate(user=other_user)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_201_CREATED
        assert TrialLesson.objects.get().student == other_student

    def test_if_lesson_belongs_to_other_student_returns_404(
        self, delete_lesson, student_user
    ):
        _, other_student = make_student()
        lesson = make_lesson(other_student)

        response = delete_lesson(lesson.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert TrialLesson.objects.filter(id=lesson.id).exists()

    def test_if_id_does_not_exist_returns_404(self, delete_lesson, student_user):
        response = delete_lesson(999999)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestWeeklyClassTrialLessonClash:
    def test_if_other_students_upcoming_trial_lesson_holds_slot_post_returns_400(
        self, create_class, student_user
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_lesson(other_student, starts_at)
        subject = make_subject()

        response = create_class(class_payload(subject, starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [CLASH_MESSAGE]
        assert not WeeklyClass.objects.exists()

    def test_if_own_upcoming_trial_lesson_holds_slot_post_returns_400(
        self, create_class, student_user
    ):
        _, student = student_user
        starts_at = future_hour()
        make_lesson(student, starts_at)
        subject = make_subject()

        response = create_class(class_payload(subject, starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [CLASH_MESSAGE]

    def test_if_completed_trial_lesson_is_still_upcoming_post_returns_400(
        self, create_class, student_user
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_lesson(other_student, starts_at, completed=True)

        response = create_class(class_payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [CLASH_MESSAGE]

    def test_if_trial_lesson_has_passed_post_returns_201(
        self, create_class, student_user
    ):
        _, other_student = make_student()
        starts_at = past_hour()
        make_lesson(other_student, starts_at)

        response = create_class(class_payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_201_CREATED
        assert WeeklyClass.objects.count() == 1

    @pytest.mark.parametrize("offset", [{"hours": 1}, {"days": 1}])
    def test_if_trial_lesson_is_at_other_hour_or_weekday_post_returns_201(
        self, create_class, student_user, offset
    ):
        _, other_student = make_student()
        starts_at = future_hour()
        make_lesson(other_student, starts_at)

        response = create_class(
            class_payload(make_subject(), starts_at + datetime.timedelta(**offset))
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_if_class_is_moved_onto_trial_lesson_slot_put_returns_400(
        self, api_client, student_user
    ):
        _, student = student_user
        _, other_student = make_student()
        trial_at = future_hour()
        make_lesson(other_student, trial_at)
        other_slot = trial_at + datetime.timedelta(days=1, hours=1)
        weekly_class = make_weekly_class(student, other_slot)

        response = api_client.put(
            f"/classes/{weekly_class.id}/",
            class_payload(weekly_class.subject, trial_at),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [CLASH_MESSAGE]
        weekly_class.refresh_from_db()
        assert weekly_class.time == other_slot.time()

    def test_if_class_is_moved_onto_trial_lesson_slot_patch_returns_400(
        self, api_client, student_user
    ):
        _, student = student_user
        _, other_student = make_student()
        trial_at = future_hour()
        make_lesson(other_student, trial_at)
        # Same weekday as the trial lesson, different hour.
        same_day_other_hour = trial_at.replace(hour=(trial_at.hour + 1) % 24)
        weekly_class = make_weekly_class(student, same_day_other_hour)

        response = api_client.patch(
            f"/classes/{weekly_class.id}/",
            {"time": trial_at.strftime("%H:00")},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [CLASH_MESSAGE]

    def test_if_class_is_moved_to_free_slot_patch_returns_200(
        self, api_client, student_user
    ):
        _, student = student_user
        _, other_student = make_student()
        trial_at = future_hour()
        make_lesson(other_student, trial_at)
        weekly_class = make_weekly_class(
            student, trial_at + datetime.timedelta(days=1, hours=1)
        )

        response = api_client.patch(
            f"/classes/{weekly_class.id}/",
            {"day": DayOfWeek.values[(trial_at.weekday() + 3) % 7]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestTrialLessonCascades:
    def test_if_user_is_deleted_trial_lesson_is_deleted(self):
        user, student = make_student()
        lesson = make_lesson(student)

        user.delete()

        assert not TrialLesson.objects.filter(id=lesson.id).exists()

    def test_if_student_is_deleted_trial_lesson_is_deleted(self):
        _, student = make_student()
        lesson = make_lesson(student)

        student.delete()

        assert not TrialLesson.objects.filter(id=lesson.id).exists()

    def test_if_subject_has_trial_lesson_delete_raises_protected_error(self):
        _, student = make_student()
        lesson = make_lesson(student)

        with pytest.raises(ProtectedError):
            lesson.subject.delete()

        assert Subject.objects.filter(id=lesson.subject_id).exists()

    def test_if_level_has_trial_lesson_delete_raises_protected_error(self):
        _, student = make_student()
        subject = make_subject(levels=("a_level",))
        make_lesson(student, subject=subject, level=get_level("a_level"))

        with pytest.raises(ProtectedError):
            get_level("a_level").delete()

        assert Level.objects.filter(code="a_level").exists()


@pytest.mark.django_db
class TestTrialLessonModel:
    def test_if_student_has_second_lesson_save_raises_integrity_error(self):
        _, student = make_student()
        subject = make_subject()
        make_lesson(student, future_hour(days=4), subject=subject)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_lesson(student, future_hour(days=5), subject=subject)

        assert TrialLesson.objects.count() == 1

    def test_if_starts_at_is_duplicated_save_raises_integrity_error(self):
        _, student = make_student()
        _, other_student = make_student()
        subject = make_subject()
        starts_at = future_hour()
        make_lesson(student, starts_at, subject=subject)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_lesson(other_student, starts_at, subject=subject)

        assert TrialLesson.objects.count() == 1

    @pytest.mark.parametrize("change", [{"minute": 30}, {"second": 30}])
    def test_if_starts_at_is_not_full_hour_save_raises_integrity_error(self, change):
        _, student = make_student()

        with pytest.raises(IntegrityError), transaction.atomic():
            make_lesson(student, future_hour().replace(**change))

        assert not TrialLesson.objects.exists()

    def test_if_starts_at_is_not_full_hour_full_clean_raises(self):
        _, student = make_student()
        subject = make_subject()
        lesson = TrialLesson(
            student=student,
            subject=subject,
            level=subject.levels.first(),
            starts_at=future_hour().replace(minute=30),
        )

        with pytest.raises(ValidationError) as error:
            lesson.full_clean()

        assert "starts_at" in error.value.message_dict

    def test_if_level_is_not_in_subject_full_clean_raises(self):
        _, student = make_student()
        subject = make_subject(levels=("o_level",))
        lesson = TrialLesson(
            student=student,
            subject=subject,
            level=get_level("a_level"),
            starts_at=future_hour(),
        )

        with pytest.raises(ValidationError) as error:
            lesson.full_clean()

        assert "level" in error.value.message_dict

    def test_if_upcoming_starts_at_is_on_weekly_slot_full_clean_raises(self):
        _, student = make_student()
        _, other_student = make_student()
        starts_at = future_hour()
        make_weekly_class(other_student, starts_at)
        subject = make_subject()
        lesson = TrialLesson(
            student=student,
            subject=subject,
            level=subject.levels.first(),
            starts_at=starts_at,
        )

        with pytest.raises(ValidationError) as error:
            lesson.full_clean()

        assert "starts_at" in error.value.message_dict

    def test_if_starts_at_is_in_the_past_full_clean_accepts_it(self):
        _, student = make_student()
        subject = make_subject()
        lesson = TrialLesson(
            student=student,
            subject=subject,
            level=subject.levels.first(),
            starts_at=past_hour(),
        )

        lesson.full_clean()

    def test_if_past_starts_at_is_on_weekly_slot_full_clean_accepts_it(self):
        _, student = make_student()
        _, other_student = make_student()
        starts_at = past_hour()
        make_weekly_class(other_student, starts_at)
        subject = make_subject()
        lesson = TrialLesson(
            student=student,
            subject=subject,
            level=subject.levels.first(),
            starts_at=starts_at,
        )

        lesson.full_clean()


def subject_form(subject, levels, **overrides):
    data = {
        "name": subject.name,
        "slug": subject.slug,
        "levels": [get_level(code).pk for code in levels],
        "price_40_min": "10.00",
        "price_60_min": "15.00",
    }
    data.update(overrides)
    return SubjectAdminForm(data=data, instance=subject)


@pytest.mark.django_db
class TestSubjectAdminFormTrialLessons:
    def test_if_level_used_by_trial_lesson_is_removed_form_is_invalid(self):
        _, student = make_student()
        subject = make_subject(levels=("o_level", "a_level"))
        make_lesson(student, subject=subject, level=get_level("a_level"))

        form = subject_form(subject, levels=("o_level",))

        assert not form.is_valid()
        assert "levels" in form.errors

    def test_if_level_used_by_trial_lesson_is_kept_form_is_valid(self):
        _, student = make_student()
        subject = make_subject(levels=("o_level", "a_level"))
        make_lesson(student, subject=subject, level=get_level("a_level"))

        form = subject_form(subject, levels=("a_level",))

        assert form.is_valid(), form.errors

    def test_if_level_is_used_only_by_other_subjects_trial_lesson_form_is_valid(self):
        _, student = make_student()
        subject = make_subject(levels=("o_level", "a_level"))
        other_subject = make_subject(levels=("o_level", "a_level"))
        make_lesson(student, subject=other_subject, level=get_level("a_level"))

        form = subject_form(subject, levels=("o_level",))

        assert form.is_valid(), form.errors


def on_weekday(weekday, days=3, hours=0):
    """A future full UTC hour that falls on the given weekday (0 = Monday)."""
    start = future_hour(days=days, hours=hours)
    return start + datetime.timedelta(days=(weekday - start.weekday()) % 7)


@pytest.mark.django_db
class TestClashOnEveryWeekday:
    @pytest.mark.parametrize("weekday", range(7))
    def test_if_trial_lesson_is_on_weekday_weekly_class_with_that_day_returns_400(
        self, create_class, student_user, weekday
    ):
        _, other_student = make_student()
        starts_at = on_weekday(weekday)
        make_lesson(other_student, starts_at)

        response = create_class(class_payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["non_field_errors"] == [CLASH_MESSAGE]

    @pytest.mark.parametrize("weekday", range(7))
    def test_if_trial_lesson_is_on_weekday_weekly_class_on_next_day_returns_201(
        self, create_class, student_user, weekday
    ):
        _, other_student = make_student()
        starts_at = on_weekday(weekday)
        make_lesson(other_student, starts_at)
        next_day = DayOfWeek.values[(weekday + 1) % 7]

        response = create_class(
            class_payload(make_subject(), starts_at, day=next_day)
        )

        assert response.status_code == status.HTTP_201_CREATED

    @pytest.mark.parametrize("weekday", range(7))
    def test_if_weekly_class_has_day_code_trial_lesson_on_that_weekday_returns_400(
        self, create_lesson, student_user, weekday
    ):
        _, other_student = make_student()
        starts_at = on_weekday(weekday)
        make_weekly_class(other_student, starts_at)

        response = create_lesson(payload(make_subject(), starts_at))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["starts_at"] == [CLASH_MESSAGE]

    @pytest.mark.parametrize("weekday", range(7))
    def test_if_weekly_class_has_day_code_trial_lesson_on_next_weekday_returns_201(
        self, create_lesson, student_user, weekday
    ):
        _, other_student = make_student()
        make_weekly_class(other_student, on_weekday(weekday))

        response = create_lesson(
            payload(make_subject(), on_weekday((weekday + 1) % 7))
        )

        assert response.status_code == status.HTTP_201_CREATED
