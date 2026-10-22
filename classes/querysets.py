import datetime

from django.db import models
from django.db.models.functions import (
    ExtractHour,
    ExtractMinute,
    ExtractWeekDay,
    Mod,
)
from django.utils import timezone

from .timeslots import (
    DJANGO_WEEK_DAY,
    MINUTES_PER_DAY,
    MINUTES_PER_WEEK,
    day_rank,
    utc_offset_minutes,
)


class BookingQuerySet(models.QuerySet):
    def with_mine(self, student):
        # Whether each booking is the student's own, without loading whose
        # it is: the availability route returns every student's bookings.
        return self.annotate(
            mine=models.ExpressionWrapper(
                models.Q(student=student), output_field=models.BooleanField()
            )
        )


class WeeklyClassQuerySet(BookingQuerySet):
    def for_student(self, student):
        # One student's classes, with what their serializer reads loaded.
        return (
            self.filter(student=student)
            .select_related("subject", "level")
            .prefetch_related("subject__levels")
        )

    def in_week_order(self):
        return self.order_by(day_rank(), "time")

    def with_week_minute(self, tz, at=None):
        # The minute of the week each class starts on as it reads in tz at
        # the moment at (Monday 00:00 is 0): slot_in_zone() in SQL, to order
        # and filter by.
        return self.annotate(
            week_minute=Mod(
                day_rank() * MINUTES_PER_DAY
                + ExtractHour("time") * 60
                + ExtractMinute("time")
                + utc_offset_minutes(tz, at)
                + MINUTES_PER_WEEK,
                MINUTES_PER_WEEK,
                output_field=models.IntegerField(),
            )
        )


class TrialLessonQuerySet(BookingQuerySet):
    def for_student(self, student):
        # One student's lesson, with what its serializer reads loaded.
        return (
            self.filter(student=student)
            .select_related("subject", "level")
            .prefetch_related("subject__levels")
        )

    def upcoming(self):
        return self.filter(starts_at__gt=timezone.now())

    def on_weekly_slot(self, day, time):
        # Lessons start on the full hour, so the hour alone identifies the
        # slot.
        return self.annotate(
            utc_week_day=ExtractWeekDay("starts_at", tzinfo=datetime.UTC),
            utc_hour=ExtractHour("starts_at", tzinfo=datetime.UTC),
        ).filter(utc_week_day=DJANGO_WEEK_DAY[day], utc_hour=time.hour)
