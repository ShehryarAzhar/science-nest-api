from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AvailabilityView,
    ScheduleView,
    SubjectViewSet,
    TrialLessonViewSet,
    WeeklyClassViewSet,
)

router = SimpleRouter()
router.register("subjects", SubjectViewSet)
router.register("classes", WeeklyClassViewSet, basename="weekly-class")
router.register("trial-lessons", TrialLessonViewSet, basename="trial-lesson")

urlpatterns = [
    # Not viewsets, so they sit beside the router's routes.
    path("schedule/", ScheduleView.as_view(), name="schedule"),
    path("availability/", AvailabilityView.as_view(), name="availability"),
    *router.urls,
]
