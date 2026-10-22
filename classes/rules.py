from django.apps import apps

from .constants import LEVEL_NOT_IN_SUBJECT_MESSAGE, TIMESLOT_TAKEN_MESSAGE
from .timeslots import utc_slot

# The models call these from clean(), so this module cannot import them: the
# clash checks look their model up in the app registry instead.


def level_not_in_subject_error(subject, level):
    # The one place the rule lives: the models' clean() and the serializers
    # all ask here. Returns the message, or None when the level is fine.
    if subject.levels.filter(pk=level.pk).exists():
        return None
    return LEVEL_NOT_IN_SUBJECT_MESSAGE.format(subject=subject, level=level)


def weekly_class_clash_error(starts_at):
    # A trial lesson cannot start on a weekday + hour any weekly class holds.
    # TrialLesson.clean() and the serializer both ask here. Returns the
    # message, or None when the slot is free.
    WeeklyClass = apps.get_model("classes", "WeeklyClass")
    day, time = utc_slot(starts_at)
    if WeeklyClass.objects.filter(day=day, time=time).exists():
        return TIMESLOT_TAKEN_MESSAGE
    return None


def trial_lesson_clash_error(day, time):
    # A weekly class cannot take a slot an upcoming trial lesson occupies.
    # WeeklyClass.clean() and the serializer both ask here. Returns the
    # message, or None when the slot is free.
    TrialLesson = apps.get_model("classes", "TrialLesson")
    if TrialLesson.objects.upcoming().on_weekly_slot(day, time).exists():
        return TIMESLOT_TAKEN_MESSAGE
    return None
