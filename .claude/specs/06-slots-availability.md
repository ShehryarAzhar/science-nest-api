# Spec: Slots Availability

## Overview
The booking pickers on the frontend do not know which slots are taken, so a student finds out only after submitting a weekly class or a trial lesson and getting "This timeslot is already booked." This feature adds `GET /availability/`, which returns every taken slot, in UTC, so the pickers can grey them out first. It returns only times, plus a `mine` flag on the logged-in student's own bookings so a picker can keep the slot of the booking being edited selectable. It stores nothing new and changes no booking rule: it reads the `WeeklyClass` and `TrialLesson` rows the earlier features created, and the booking routes keep their own clash checks, because a slot can still be taken between loading the picker and submitting. It is built now because all the bookings it reports, and the clash rules it mirrors, exist (features 3 and 4).

## Depends on
- `.claude/specs/01-users.md` — the `Student` profile and JWT authentication.
- `.claude/specs/03-weekly-classes.md` — the `WeeklyClass` model, its `(day, time)` uniqueness, `in_week_order()` and `IsStudent`.
- `.claude/specs/04-trial-lessons.md` — the `TrialLesson` model, `upcoming()`, and the two clash rules between weekly classes and trial lessons.

All three are implemented.

## Requirements
`CLAUDE.md` has no section for this feature yet; it is added as Product requirements 6 during implementation (see Files to change). The rules below come from the feature request and the decisions the user made on it.

1. `GET /availability/` returns the taken slots, so the frontend can grey them out in its weekly class and trial lesson pickers.
2. Every day, time and date-time is UTC, as everywhere in the API.
3. It returns only times. It never returns who booked a slot, the student, the user, a booking id, the subject, the level, the duration, the completed flag, or any other booking data.
4. The logged-in student's own bookings are marked with `mine: true`; every other booking has `mine: false`.
5. Only logged-in students can use it (`IsAuthenticated` + `IsStudent`), like the booking routes: an anonymous request gets 401, a logged-in user without a Student gets 403.
6. It is read-only.
7. It does not replace the server-side checks: `/classes/` and `/trial-lessons/` keep their clash validation and their error messages exactly as they are.

Decisions the user made on points the request left open:

8. **Grouped by kind of booking, not by picker** — the response has two lists, `weekly_classes` and `trial_lessons`. They cannot be merged into one weekly list because the two kinds block different things (the server rules from features 3 and 4):
   - a weekly class blocks its weekday + hour for new weekly classes and for trial lessons on every date;
   - an upcoming trial lesson blocks its weekday + hour for weekly classes, but for other trial lessons it blocks only its exact `starts_at` (a trial lesson on Monday 26 Oct 02:00 does not block one on Monday 2 Nov 02:00).
9. **Trial lesson items carry their weekday and hour** — besides `starts_at`, each trial lesson item has `day` and `time`: the weekday and time of `starts_at` in UTC, in the same format as a weekly class, so the weekly class picker does not have to work them out.
10. **Tutor working hours are not part of this feature** — every hour of every day stays bookable, and the endpoint returns no working hours. Limiting the tutor's hours would change the booking rules and need its own model and admin screen, so it is a possible later feature.

Choices of this spec that follow the earlier features:

11. **Which trial lessons count** — only upcoming ones: `starts_at` later than now, whether or not they are marked completed. This is the same test the clash rules use (`TrialLesson.objects.upcoming()`). A trial lesson whose start time has been reached blocks nothing and is left out, the student's own included.
12. **Weekly classes** — every student's weekly classes are listed; a weekly class never expires.
13. **No duplicates** — the database already holds at most one weekly class per `(day, time)` and one trial lesson per `starts_at`, so each list has one item per booking.
14. **Order** — `weekly_classes` is ordered Monday to Sunday, then by time, as on `/classes/`; `trial_lessons` by `starts_at`, earliest first.
15. **Formats** — `day` is the code (`monday` to `sunday`), `time` is `"HH:MM:SS"` as on `/classes/`, `starts_at` is ISO 8601 ending in `Z` as on `/trial-lessons/`, `mine` is a JSON boolean. There is no `day_display`.
16. **Empty** — with no bookings anywhere the response is `{"weekly_classes": [], "trial_lessons": []}` with 200.

What `mine` means for the frontend (documented in `CLAUDE.md`; nothing on the server depends on it):

17. `mine` says only that the slot is held by one of the student's own bookings, not which one. When editing weekly class X, the picker frees only X's own `day` + `time`; the student's other weekly classes and their own upcoming trial lesson still block, because the server rejects those slots for them too. When editing their trial lesson, the picker frees its own `starts_at`.

## Deferred rules
No deferred rules, and no earlier spec deferred a rule to this one.

Possible later feature, not deferred from this one: tutor working hours set in the Django admin (Requirements 10).

## Routes
- `GET /availability/` — every taken weekly slot and every upcoming trial lesson time, in UTC, with `mine` on the student's own — authenticated student

An anonymous request returns 401; an authenticated user without a Student returns 403. `POST`, `PUT`, `PATCH` and `DELETE` return 405 for a student.

## Models and database changes
No database changes: no new model, field or constraint, and no migration. `uv run python manage.py makemigrations --check` must still report nothing to generate.

`Student`, `Level`, `Subject`, `WeeklyClass`, `TrialLesson` and `core.User` are unchanged.

One helper, which does not touch the schema, may be added to `classes/timeslots.py`: `utc_slot(starts_at)`, returning the `(day, time)` a date-time falls on in UTC (`DayOfWeek.values[starts_at.weekday()]` and `starts_at.time()` after `astimezone(datetime.UTC)`). `weekly_class_clash_error()` in `classes/rules.py` already does this conversion inline; it uses the helper instead, so the trial lesson item's `day` + `time` and the clash rule cannot disagree. Its behaviour does not change.

## Serializers and validation
All in the existing `classes/serializers.py`, output only. The route takes no input, so there is no validation.

`classes.serializers.TakenWeeklySlotSerializer` (plain `serializers.Serializer`):
- `day` — `ChoiceField(choices=DayOfWeek.choices)`, read-only.
- `time` — `TimeField`, read-only.
- `mine` — `BooleanField`, read-only.

`classes.serializers.TakenTrialSlotSerializer` (plain `serializers.Serializer`):
- `starts_at` — `DateTimeField`, read-only.
- `day`, `time` — read-only, the UTC weekday and time of `starts_at` (from `utc_slot()`).
- `mine` — `BooleanField`, read-only.

`classes.serializers.AvailabilitySerializer` (plain `serializers.Serializer`):
- `weekly_classes` — `TakenWeeklySlotSerializer(many=True, read_only=True)`.
- `trial_lessons` — `TakenTrialSlotSerializer(many=True, read_only=True)`.

None of them is a `ModelSerializer` and none uses `fields = "__all__"`: the fields are listed by hand so nothing else of a booking can leak out.

A response looks like (Monday 26 Oct 2026; the student owns the Monday class and the 28 Oct trial lesson):

```json
{
  "weekly_classes": [
    {"day": "monday", "time": "02:00:00", "mine": true},
    {"day": "tuesday", "time": "14:00:00", "mine": false}
  ],
  "trial_lessons": [
    {"starts_at": "2026-10-27T09:00:00Z", "day": "tuesday", "time": "09:00:00", "mine": false},
    {"starts_at": "2026-10-28T16:00:00Z", "day": "wednesday", "time": "16:00:00", "mine": true}
  ]
}
```

How the frontend uses it:

| Picker | Greyed out |
| --- | --- |
| Weekly class | every `weekly_classes` `day` + `time`, and the `day` + `time` of every `trial_lessons` item |
| Trial lesson | every date that falls on a `weekly_classes` `day` + `time`, and every exact `starts_at` in `trial_lessons` |

## Views and URLs
`classes.views.AvailabilityView`:
- Base class: `rest_framework.views.APIView`. It reads two models and maps onto no model's CRUD (API conventions).
- `permission_classes = [IsAuthenticated, IsStudent]`, in that order.
- Only `get()` is defined; every other method answers 405.
- `get()` reads `request.user.student` only to set `mine`, and loads:
  - the weekly classes: `WeeklyClass.objects.all()` (every student's) in `in_week_order()`, reading only `day`, `time` and whether `student_id` is the logged-in student's (e.g. `.values()` / `only()` with a `mine` annotation such as `Q(student=student)` in an `ExpressionWrapper`, or a comparison in Python on `student_id`). No `select_related` of the student, user, subject or level;
  - the trial lessons: `TrialLesson.objects.upcoming()` (every student's) ordered by `starts_at`, reading only `starts_at` and the same `mine`.
- It returns `AvailabilitySerializer` data with 200.
- The number of queries is fixed: it does not grow with the number of bookings.

`classes/urls.py`: added beside the router's routes, like the schedule: `path("availability/", AvailabilityView.as_view(), name="availability")`.

`config/urls.py` is unchanged: it already mounts `classes.urls` at the root, giving `/availability/`.

## Admin
No admin changes. The feature adds no model and nothing admin-only; an admin already sees every booking on the existing admin pages.

## Files to change
- `classes/serializers.py` — add `TakenWeeklySlotSerializer`, `TakenTrialSlotSerializer` and `AvailabilitySerializer`
- `classes/views.py` — add `AvailabilityView`
- `classes/urls.py` — add the `availability/` path
- `classes/timeslots.py` — add `utc_slot(starts_at)`
- `classes/rules.py` — `weekly_class_clash_error()` uses `utc_slot()`; behaviour unchanged
- `classes/querysets.py` — only if the `mine` annotation is put on the querysets (e.g. `with_mine(student)`) rather than in the view
- `CLAUDE.md`:
  - Product requirements: the opening line ("All five requirements are built") becomes six; add requirement 6, **Slots availability**, with Requirements 1–17 above, including the frontend table and the meaning of `mine`
  - API conventions: the scoping bullet names the availability route as the second exception after the clash checks: it reads every student's bookings but returns only their times and `mine`
  - Feature workflow table: add `slots-availability` | 6 | `.claude/specs/06-slots-availability.md` | `/availability/` | `classes/tests/test_availability.py`
  - Architecture: `classes/` mentions `AvailabilityView`, an `APIView` on a plain `path()` beside the router like `ScheduleView`, and `utc_slot()` in `timeslots.py`
  - "Implemented vs Stub Routes": a new "Slots availability" table with `GET /availability/` marked Implemented
- `.claude/commands/create-spec.md`, `.claude/commands/test-feature.md`, `.claude/commands/code-review-feature.md` — add `slots-availability` to their feature tables, argument hints and lists of known features
- `.claude/agents/nest-test-writer.md` — the URL list gains `/availability/`, the file names gain `test_availability.py`, and a **Slots availability** block of rules is added beside **My schedule**
- `.claude/agents/nest-security-reviewer.md` — `/availability/` joins the routes that need `IsAuthenticated` + `IsStudent`; add the rule that it reads every student's bookings but exposes only `day`, `time`, `starts_at` and `mine`, and has no write method
- `.claude/agents/nest-quality-reviewer.md` — the app description and the "does not map onto CRUD" example mention availability; add the rule that a trial lesson's UTC weekday + hour comes from `utc_slot()`, shared with the clash rule
- Any other command or agent file that turns out to carry these rules gets the same update

## Files to create
No new application files.

`classes/tests/test_availability.py` is created later by `/test-feature slots-availability`, not during implementation.

## New dependencies
No new dependencies.

## Rules for implementation
- Money is stored in `DecimalField`, never `FloatField`
- Reference the user via `settings.AUTH_USER_MODEL` / `get_user_model()`, never `django.contrib.auth.models.User`
- Every view declares its own `permission_classes`; no default permission class is set
- Booking querysets are scoped to `request.user`; timeslot clash checks look at every user's bookings
- Booking rules are enforced on the server in serializers/models, backed by a database constraint where possible
- Prefer `ModelViewSet` on a DRF router; subjects use `ReadOnlyModelViewSet`
- No teacher- or admin-facing endpoints; register every model in `admin.py` instead
- No templates or server-rendered pages
- Update the "Implemented vs Stub Routes" tables in `CLAUDE.md` in the same change
- The availability route is the one route besides the clash checks that reads every student's bookings; the only data it returns from them is `day`, `time`, `starts_at` and `mine`. No id, student, user, subject, level, duration, completed flag or price, and no count per student
- `mine` compares with `request.user.student`; the route accepts no student, user or id in the path or the query string
- Never assume `request.user.student` exists outside code guarded by `IsStudent`
- Upcoming means `starts_at` later than now, through `TrialLesson.objects.upcoming()`; do not filter on `completed`, and do not write a second definition of upcoming
- A trial lesson's UTC weekday + hour is computed in one place, `utc_slot()`, which `weekly_class_clash_error()` also uses
- The week order is `in_week_order()`; do not write a second one
- The view is an `APIView` with only `get()`; do not register it on the router and do not add a write method
- Do not change `/classes/`, `/trial-lessons/`, `/schedule/` or `/subjects/`, their serializers, their validation or their error messages
- Every day, time and date-time is returned in UTC as stored; do not convert to another timezone and do not change `TIME_ZONE` or `USE_TZ`
- Do not add fields the spec does not list (no `day_display`, no free slots, no working hours, no `is_locked`)
- No pagination, no filters and no date window on the route
- Do not write tests during implementation

## Tests
Covered by `classes/tests/test_availability.py`, written and run with `/test-feature slots-availability`, not as part of implementation. A test student is `baker.make(get_user_model())` plus `baker.make(Student, user=user)`. Bookings are built with `baker.make`, each with a level that is one of its subject's levels (seeded levels fetched with `Level.objects.get(code=...)`), each weekly class on its own day and time, and no trial lesson on a weekly class's weekday + hour. A trial lesson's `starts_at` is built relative to `timezone.now()`, rounded to a full hour. It must cover:
- Access: `GET /availability/` returns 401 for an anonymous request and 403 for an authenticated user without a Student
- Read-only: `POST`, `PUT`, `PATCH` and `DELETE /availability/` return 405 for a student and change nothing
- Top level: 200 with exactly `weekly_classes` and `trial_lessons`
- Empty: with no bookings anywhere, both lists are `[]`
- Weekly class item: exactly `day`, `time` and `mine`, in UTC as stored
- Trial lesson item: exactly `starts_at`, `day`, `time` and `mine`; `starts_at` in UTC; `day` and `time` are its UTC weekday and time, including a lesson whose UTC weekday differs from its weekday in Asia/Karachi (e.g. Monday 21:00 UTC)
- Every student: another student's weekly classes and upcoming trial lessons are listed with `mine: false`
- Mine: the student's own weekly classes and own upcoming trial lesson are listed with `mine: true`; the same booking reads `mine: false` for a second student
- No student data: no item has any key besides those above, and nothing in the response contains another student's username, email, id, subject or level
- Past trial lessons: a trial lesson whose `starts_at` has passed, the student's own included, is not listed; a completed trial lesson whose `starts_at` is still ahead is listed
- Order: `weekly_classes` is Monday to Sunday, then by time; `trial_lessons` is earliest `starts_at` first
- Live: a weekly class booked, moved or deleted, and a trial lesson booked or deleted, shows up in the next `GET /availability/`
- Query count: `GET /availability/` runs the same number of queries with one booking as with several bookings of several students
- Booking routes unchanged: booking a slot listed as taken is still rejected by `/classes/` and `/trial-lessons/` with "This timeslot is already booked."

## Definition of done
- [ ] `uv run python manage.py makemigrations --check` reports no missing migrations
- [ ] Each route returns the expected status for an anonymous request (`GET /availability/` returns 401)
- [ ] The feature's routes are marked Implemented in `CLAUDE.md`
- [ ] A superuser's token gets 403 on `GET /availability/`
- [ ] With no bookings, a student gets 200 with `{"weekly_classes": [], "trial_lessons": []}`
- [ ] After student A books a Tuesday 14:00 weekly class, student B's `GET /availability/` lists `{"day": "tuesday", "time": "14:00:00", "mine": false}` and student A's lists it with `mine: true`
- [ ] After student A books a trial lesson at `2026-10-27T09:00:00Z` (any future full hour), both students see it in `trial_lessons` with its UTC `day` and `time`, and `mine` true only for A
- [ ] A trial lesson whose start time has passed is not listed
- [ ] No item in the response has any key besides `day`, `time`, `starts_at` and `mine`
- [ ] `POST /availability/` with a student's token returns 405
- [ ] `/classes/` and `/trial-lessons/` still reject a taken slot with the same error as before
- [ ] `uv run pytest classes/tests/test_availability.py` passes (after `/test-feature slots-availability`)
- [ ] `uv run pytest` passes (the `rules.py` change leaves the weekly class and trial lesson tests green)
