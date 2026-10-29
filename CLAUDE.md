# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Backend API for Science Nest, a science tutoring web application. This repo is backend only: a separate Next.js + TypeScript frontend consumes the API, so there are no templates or server-rendered pages here.

## Stack

Django 6.1 + Django REST Framework API on Python 3.14, backed by MySQL. Dependencies are managed with `uv` (`pyproject.toml` / `uv.lock`); there is no `requirements.txt`.

## Product requirements

All six requirements are built (see Implemented vs Stub Routes). The numbering 1–6 matches the spec numbers (requirement 2 is `.claude/specs/02-subjects.md`) and is referenced by the slash commands ("Product requirements 4"), so keep it stable.

1. **Users and student profile** — a user registers with username, email, password, first and last name and a phone number, and logs in with a JWT. Auth is delegated to Djoser + SimpleJWT; Architecture > Auth describes how it is built.
   - Email is unique.
   - The phone number is required at registration: an optional `+` followed by 7 to 15 digits. Surrounding whitespace is rejected, not stripped. It is not unique.
   - Registering creates the user's Student profile, which holds the phone number. The user and the Student are created together or not at all.
   - Users created outside registration (`createsuperuser`, the Django admin) have no phone number and no Student.
   - A student can read their own details, including the phone number, at `/auth/users/me/`, and edit their email, first name and last name there. Username and phone number cannot be changed through the API; the phone number is edited in the Django admin.
   - A student can delete their own account, which deletes their Student.
   - A user who forgot their password resets it by email, in two public steps:
     - `POST /auth/users/reset_password/` takes `email` and always answers 204, whether or not the email is registered, so the route cannot be used to find out which emails exist. A missing or malformed email is a 400. The reset email is sent only to an active user with a usable password.
     - The email holds a link to the frontend, `{protocol}://{frontend domain}/reset-password/{uid}/{token}` (e.g. `http://localhost:3000/reset-password/MQ/abc-123`). The link is valid for one hour.
     - `POST /auth/users/reset_password_confirm/` takes `uid`, `token` and `new_password` and answers 204. A wrong `uid`, a wrong, expired or already used `token`, or a `new_password` that fails the password validators is a 400 on that field, and the password is not changed. There is no retype field.
     - A link works once. After a reset the old password no longer logs in, and a "your password has been changed" email is sent.
     - `POST /auth/users/reset_password/` is limited to 5 requests per hour per IP address; the next one gets 429. No other route is limited.
   - Whenever a password changes (a reset, or `set_password`), every JWT issued before the change is rejected with 401, so the user logs in again everywhere.
2. **Subjects** — each subject has two USD prices: one for a 40-minute class and one for a 60-minute class. Store prices in `DecimalField`, never `FloatField`. The API is read-only for subjects (list and retrieve); admins create and edit them in the Django admin site, so use `ReadOnlyModelViewSet` and register the model in `classes/admin.py`.
   - The subject routes are public: anyone can list and retrieve subjects without logging in.
   - A subject has a name, a slug, a description, one or more levels and the two prices, nothing else. The API returns them as `id`, `name`, `slug`, `description`, `levels`, `price_40_min` and `price_60_min`.
   - The slug is the subject's public URL on the frontend (e.g. `/subjects/chemistry`). It is required and unique: lowercase letters and digits, in groups separated by single hyphens (`chemistry`, `a-level-maths`); capitals, underscores and a leading, trailing or double hyphen are rejected.
   - The slug must stay stable: renaming a subject does not change it, and it is never regenerated from the name on save. The Django admin prefills it from the name when a subject is added; on the edit form it stays as it is unless the admin changes it by hand.
   - The description is plain text and may be blank. It is stored as typed (no HTML, no Markdown processing) and edited in the Django admin in a multi-line box.
   - One subject is retrieved by its slug, `GET /subjects/{slug}/`, not by its id: an unknown slug is a 404, and so is the numeric id.
   - A level is a level the tutor teaches the subject at. There are four, created by a data migration: `o_level` (O Level), `a_level` (A Level), `all_levels` (All Levels (1-O Level)) and `university` (University Level). A subject has one or more of them, chosen in the Django admin. The API returns them as `levels`, a list of objects with `code` and `name`, in the order listed here.
   - The name is unique.
   - A price is zero or more: a negative price is rejected, a free subject (0.00) is allowed. The two prices are independent; neither has to be lower than the other.
3. **Weekly class scheduling** — a user books a weekly recurring class by choosing subject, level, day of the week, time, and a duration of 40 or 60 minutes.
   - A weekly class has exactly one level: the level the student wants to study the subject at. It must be one of the chosen subject's levels; otherwise the request is rejected with a validation error on `level`. This is checked on every write: a `PATCH` that changes only the subject checks the class's current level, and a `PATCH` that changes only the level checks the class's current subject.
   - A request sends `level` as the level's code (e.g. `"a_level"`); a response returns it as an object with `code` and `name`, like the items of a subject's `levels`.
   - A level used by a weekly class or a trial lesson cannot be deleted, and in the Django admin a level cannot be removed from a subject while weekly classes or trial lessons of that subject use it.
   - A user may book several classes of the same subject in one week.
   - Two classes cannot be booked in the same timeslot. This is enforced across all users, not per student: once any student holds a weekday + hour slot, nobody else can book it.
   - Classes start only on the full hour (4:00, 5:00, ...); reject any other time. The day and time are UTC.
   - Reject the booking if an upcoming trial lesson (any student's) occupies that weekday and hour, on a new booking and on an edit. A trial lesson whose start time has passed no longer blocks the slot.
   - A weekly class belongs to a Student, not directly to the user. A logged-in user without a Student gets 403 on every `/classes/` route. Deleting the student deletes their classes.
   - The day of the week is a code, `monday` to `sunday`. The API returns the code as `day` and the label as `day_display`.
   - A request sends `subject` as the subject's id; a response returns it as a nested object with `id`, `name`, `slug` and `levels` (the same list of `code` and `name` objects as `/subjects/`), and no prices or description.
   - A student can edit a weekly class (subject, level, day, time, duration) under the same rules as a new booking.
   - A subject that still has weekly classes cannot be deleted.
4. **Trial lessons** — a user books a trial lesson by choosing a subject, a level and a specific date and time. A trial lesson lasts 60 minutes, is free, and must start on the full hour like weekly classes.
   - The date and time are one field, `starts_at`, an ISO 8601 date-time in UTC (e.g. `"2026-10-13T02:00:00Z"`), not a separate date and time. There is no duration or price field.
   - A trial lesson has exactly one level, under the same rules as a weekly class: it must be one of the chosen subject's levels (otherwise a validation error on `level`, checked on every write including a `PATCH` of only the subject or only the level), a request sends it as the level's code, and a response returns it as an object with `code` and `name`.
   - A request sends `subject` as the subject's id; a response returns it as a nested object with `id`, `name`, `slug` and `levels`, and no prices or description, as on a weekly class.
   - A trial lesson belongs to a Student, not directly to the user. A logged-in user without a Student gets 403 on every `/trial-lessons/` route. Deleting the student deletes their trial lesson.
   - Each student can book only one trial lesson; reject a second booking on the server and back it with a database uniqueness constraint (the one-to-one from the trial lesson to the Student, which is itself one-to-one with the user).
   - A booking whose date and time have already passed is rejected, on a new booking and on an edit.
   - A trial lesson can be marked completed, but only in the Django admin; the completed flag is read-only in the API.
   - While the trial lesson is not completed and its date and time have not passed, the student can edit or delete it. Deleting it frees the student to book another.
   - Once it is marked completed or its date and time have passed, it is locked: the student cannot edit or delete it through the API (403, "This trial lesson can no longer be changed."), and because it still counts as their one trial lesson, they cannot create another. It stays readable. Its date and time have passed once its start time is reached.
   - Reject the booking if any student's weekly class occupies that time (same weekday and hour as the chosen date and time, in UTC).
   - Reject the booking if any student's trial lesson is already booked at that time.
   - A subject or a level that a trial lesson uses cannot be deleted.
5. **My schedule** — returns the logged-in user's schedule together with their total cost per week. Trial lessons are free and add nothing to it. The weekly cost is the sum of the prices of all the user's weekly classes, each priced by its own duration (the subject's 40-minute price or its 60-minute price).
   - `GET /schedule/` is the only route; it is read-only. The response has three parts: `weekly_classes` (a list), `trial_lesson` (one object, or `null` when the student has none) and `weekly_cost`.
   - Each item of `weekly_classes` has the fields it has on `/classes/` plus `price`, its own price. `weekly_cost` is the sum of those prices. `/classes/` itself still returns no price.
   - `weekly_classes` is ordered Monday to Sunday, then by time. With no weekly classes it is an empty list and `weekly_cost` is 0.
   - `trial_lesson` has exactly the fields it has on `/trial-lessons/` and no price. It is shown even when it is completed or its date and time have passed.
   - Prices are read from the subject on every request; no price or total is stored. When an admin changes a subject's price, the schedule shows the new price and total from then on.
   - A logged-in user without a Student gets 403 on `/schedule/`.
6. **Slots availability** — returns every taken slot, in UTC, so the frontend can grey them out in its booking pickers instead of the student finding out only after submitting.
   - `GET /availability/` is the only route; it is read-only. Logged-in students only: anonymous is 401, a logged-in user without a Student gets 403.
   - The response has two lists, grouped by kind of booking, not by picker, because the two kinds block different things: `weekly_classes` and `trial_lessons`.
     - `weekly_classes` holds every student's weekly class as `day`, `time` and `mine`, ordered Monday to Sunday, then by time.
     - `trial_lessons` holds every student's upcoming trial lesson as `starts_at`, `day`, `time` and `mine`, earliest first. `day` and `time` are the weekday and time of `starts_at` in UTC. Upcoming means its start time has not been reached, whether or not it is marked completed; a trial lesson whose start time has passed blocks nothing and is left out, the student's own included.
     - With no bookings anywhere both lists are empty. `day` is the code, `time` is `"HH:MM:SS"` as on `/classes/`, `starts_at` is ISO 8601 in UTC as on `/trial-lessons/`.
     - e.g. `{"weekly_classes": [{"day": "tuesday", "time": "14:00:00", "mine": false}], "trial_lessons": [{"starts_at": "2026-10-27T09:00:00Z", "day": "tuesday", "time": "09:00:00", "mine": true}]}`
   - It returns only times. It never returns who booked a slot, a booking id, the subject, the level, the duration, the completed flag or any other booking or student data.
   - `mine` is `true` on the logged-in student's own bookings and `false` on everyone else's. It says only that the slot is the student's, not which booking holds it.
   - How the frontend uses it:
     - Weekly class picker: grey out every `weekly_classes` day + time and the `day` + `time` of every `trial_lessons` item. When editing weekly class X, only X's own day + time stays selectable; the student's other classes and their own upcoming trial lesson still block it, as the server rejects them.
     - Trial lesson picker: grey out every date that falls on a `weekly_classes` day + time, and every exact `starts_at` in `trial_lessons` (a trial lesson does not block the same weekday + hour on other dates). When editing their trial lesson, its own `starts_at` stays selectable.
   - It does not replace the server-side checks: a slot can be taken between loading the picker and submitting, so `/classes/` and `/trial-lessons/` keep their clash validation and errors as they are.
   - There are no tutor working hours: every hour of every day is bookable, and the route returns no working hours.

## API conventions

- The API serves students only. Everything teacher- or admin-side (managing subjects, viewing and editing all students' classes and trial lessons, managing users) is done in the Django admin site, so register every model in `admin.py` and do not build teacher-facing endpoints.
- Scope every booking queryset to `request.user`; a student must never see or modify another student's classes or trial lessons. Timeslot clash checks are the exception: they must look at every user's bookings. `/availability/` is the other exception: it reads every student's bookings but returns only their `day`, `time`, `starts_at` and `mine`.
- Prefer `ModelViewSet` registered on a DRF router. When an endpoint does not map onto a model's CRUD (e.g. my schedule, which aggregates and totals), use whatever fits best (`APIView`, a generic view, or a viewset `@action`).
- Enforce booking rules (full hour, no timeslot clash) on the server in serializers/models, backed by a database constraint where possible; do not rely on the frontend.
- Every date and time in the database and the API is UTC. The server stores, compares and returns UTC; the frontend converts to and from the student's local time. Do not change `TIME_ZONE` or `USE_TZ`: DRF reads them.
- The full-hour rule and the timeslot clash checks are judged in UTC, so outside Asia/Karachi a class or trial lesson may start at :30 or :45 local time: e.g. Monday 23:00 UTC is Tuesday 04:30 in Asia/Kolkata (+5:30), Sunday 20:00 UTC is Monday 01:45 in Asia/Kathmandu (+5:45), and Australia/Adelaide is +9:30 or +10:30 depending on daylight saving. This is by design, the frontend displays it, and nothing on the server may assume an offset is a whole number of hours. A trial lesson's `starts_at` may be sent with any offset (`07:30+05:30` is 02:00 UTC and is accepted).
- The Django admin is the one exception: it shows and accepts Asia/Karachi (`ADMIN_TIME_ZONE` in settings), while still storing UTC. Architecture > Admin timezone describes how. Never call `timezone.activate()` without restoring the previous timezone (use `timezone.override()`): a timezone left active on a worker thread would leak into the next API response.

## Feature workflow

Each feature goes through the same four steps, driven by the slash commands in `.claude/commands/`:

1. `/create-spec <feature>` — needs a clean working tree. It branches `feature/<feature>` off an up-to-date `main` and writes the feature's spec file. Build features in the order of the table below: later specs pick up rules that earlier ones deferred.
2. Implement from the spec, in Plan Mode. Do not write tests during implementation. Update the route tables in the same change.
3. `/test-feature <feature>` — `nest-test-writer` writes the test file from the spec, then `nest-test-runner` runs only that file.
4. `/code-review-feature <feature>` — `nest-security-reviewer` and `nest-quality-reviewer` review the branch's changes in parallel. Apply the action plan only after the user approves it, then re-run `/test-feature`.

| Feature | Requirement | Spec file | Routes | Test file |
| --- | --- | --- | --- | --- |
| `users` | 1 | `.claude/specs/01-users.md` | `/auth/...` | `core/tests/test_users.py` |
| `subjects` | 2 | `.claude/specs/02-subjects.md` | `/subjects/` | `classes/tests/test_subjects.py` |
| `weekly-classes` | 3 | `.claude/specs/03-weekly-classes.md` | `/classes/` | `classes/tests/test_weekly_classes.py` |
| `trial-lessons` | 4 | `.claude/specs/04-trial-lessons.md` | `/trial-lessons/` | `classes/tests/test_trial_lessons.py` |
| `schedule` | 5 | `.claude/specs/05-schedule.md` | `/schedule/` | `classes/tests/test_schedule.py` |
| `slots-availability` | 6 | `.claude/specs/06-slots-availability.md` | `/availability/` | `classes/tests/test_availability.py` |

- The test runner and both reviewers are read-only and never fix anything. An implementation bug is fixed in the main session; a test bug goes back to `nest-test-writer`. Never weaken, skip or delete a test to make it pass.
- `/test-feature` and `/code-review-feature` refuse to run while the feature's routes are still marked Stub.

### Specs

- `.claude/specs/<NN>-<feature>.md`, written by `/create-spec`, is the detailed contract for one feature and records the decisions the user made on ambiguous behaviour.
- This file is the source a spec is written from. If a spec and this file contradict each other, stop and ask; do not pick one.
- A spec's "Deferred rules" section lists rules that wait for a later feature (e.g. the trial lesson clash check on weekly classes before trial lessons exist). A deferred rule is not a bug or a missing test until the spec that picks it up is implemented.
- The `users` spec, `.claude/specs/01-users.md`, was written by hand after the feature was built, not by `/create-spec`.

## Commands

```bash
uv sync                                  # install deps (including dev group) into .venv
uv run python manage.py runserver        # dev server
uv run python manage.py makemigrations   # after model changes
uv run python manage.py migrate
uv run python manage.py createsuperuser

uv run pytest                            # all tests
uv run pytest <app>/tests/               # one app
uv run pytest <app>/tests/test_<name>.py # one file
uv run pytest <app>/tests/test_<name>.py::test_name   # one test
uv run pytest -k "expression"            # by name match
```

No linter or formatter is configured.

## Environment

Settings load `.env` from the repo root via `python-dotenv`. Copy `.env.example` to `.env` and set `DB_NAME`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`. `FRONTEND_DOMAIN` and `FRONTEND_PROTOCOL` name the Next.js site that links in emails point to (default `localhost:3000`, `http`). `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` and `DEFAULT_FROM_EMAIL` configure SMTP; leave `EMAIL_HOST` empty to print emails in the terminal instead of sending them. A running MySQL server is required for the dev server, migrations, and any test that touches the database (pytest-django creates a `test_<DB_NAME>` database, so the MySQL user needs permission to create databases). MySQL's timezone tables are not required and are not assumed to be loaded: do not use anything that makes the database convert between named timezones outside UTC (e.g. `date_hierarchy` in the admin, or a `__date` / `__hour` lookup on a datetime while a non-UTC timezone is active).

## Testing

Tests run through pytest with `pytest-django` and `model-bakery` (`pytest.ini` sets `DJANGO_SETTINGS_MODULE=config.settings`). Each app keeps its tests in its own `tests/` package: `<app>/tests/__init__.py` plus `test_*.py` modules (e.g. `core/tests/test_users.py`). `pytest.ini` does not set `python_files`, so only `test_*.py` / `*_test.py` files are collected.

The `tests.py` stub that `startapp` generates is not collected and clashes with a `tests/` package of the same name — delete it when creating the app's `tests/` folder.

Tests are normally written by `nest-test-writer` through `/test-feature`. Tests written by hand follow the same conventions:

- Write tests from the spec, not from the implementation; read the source only for field names and paths.
- Shared fixtures (`api_client`, `authenticate`) live in a `conftest.py` at the repo root so both apps can use them.
- Build setup data with `model_bakery` (`baker.make(...)`), and authenticate with `force_authenticate` rather than the JWT flow.
- `baker.make(get_user_model())` does not create a Student (only registration does); when a test needs one, add `baker.make(Student, user=user)`.
- One class per action, marked `@pytest.mark.django_db` (e.g. `TestCreateWeeklyClass`), with tests named `test_if_<condition>_returns_<status>`.
- Use `rest_framework.status` constants, never bare numbers, and compare money as `Decimal`.
- Emails are never really sent in tests: assert on `django.core.mail.outbox`.
- The password reset throttle counts in Django's cache, which is not reset between tests. A test that calls `/auth/users/reset_password/` clears it first (`django.core.cache.cache.clear()`, e.g. in an autouse fixture in that test module).

## Architecture

- `config/` — the Django project (settings, root URLconf, WSGI/ASGI). There is a single settings module; no per-environment split. `config/urls.py` also sets the Django admin's site header, site title and index title ("Science Nest administration", "Science Nest admin", "Site administration").
- `core/` — custom user model, auth customisation, the registration signal that creates a user's `Student` profile, `core/throttling.py`, which rate-limits the password reset email route (see Password reset), and `core/middleware.py`, which runs the Django admin in Asia/Karachi (see Admin timezone).
- `classes/` — domain app for the `Student` profile, subjects, weekly classes, trial lessons and the schedule; its models are `Student`, `Level`, `Subject`, `WeeklyClass` and `TrialLesson`. `classes/models.py` holds only the models; the code they share sits beside it: `constants.py` (error messages and constraint names), `validators.py`, `timeslots.py` (`DayOfWeek` and the weekly slot helpers), `querysets.py` and `rules.py`. A subject's levels are a many-to-many to `Level`, whose four rows are created by the data migration `classes/migrations/0005_seed_levels.py`. `SubjectViewSet` sets `lookup_field = "slug"`, so a subject is retrieved by its slug; `subject_slug_validator` in `validators.py` holds the slug's format, which is stricter than `SlugField`'s own. `classes/permissions.py` holds `IsStudent`, which booking views list after `IsAuthenticated` so a user without a Student gets 403, and `IsTrialLessonOpen`, the object-level permission that answers 403 when a locked trial lesson is edited or deleted. The rules that compare a weekly class with a trial lesson (`weekly_class_clash_error`, `trial_lesson_clash_error`) live in `classes/rules.py`, shared by the models' `clean()` and the serializers. Its viewsets are registered on the `SimpleRouter` in `classes/urls.py`, which `config/urls.py` mounts at the root (no app prefix). The schedule and availability are not viewsets: `ScheduleView` and `AvailabilityView` are `APIView`s on plain `path()`s beside the router's routes in the same file. `AvailabilityView` reads every student's weekly classes and upcoming trial lessons; `with_mine(student)`, shared by both querysets, annotates whether each one is the student's own, and `utc_slot(starts_at)` in `timeslots.py` gives a trial lesson's UTC weekday and time, the same helper `weekly_class_clash_error` uses. `WeeklyClass.price` is the one place a class is priced by its duration; the schedule's `price` and `weekly_cost` both come from it. `for_student(student)` on `WeeklyClassQuerySet` and `TrialLessonQuerySet` is the scoped queryset (one student's bookings, with subject and levels loaded) that the viewsets and the schedule share.
- `.claude/` — Claude Code slash commands (`commands/`), subagents (`agents/`) and feature specs (`specs/`, created by `/create-spec`). See Claude Code tooling.

### Auth

Authentication is entirely delegated to Djoser + SimpleJWT; there are no hand-written auth views.

- `AUTH_USER_MODEL = "core.User"`: an `AbstractUser` subclass whose only change is making `email` unique. Always reference the user via `settings.AUTH_USER_MODEL` / `get_user_model()`.
- `config/urls.py` mounts both `djoser.urls` and `djoser.urls.jwt` under `auth/`, giving `auth/users/`, `auth/users/me/`, `auth/jwt/create/`, `auth/jwt/refresh/`, `auth/jwt/verify/`, etc.
- The `Authorization` header prefix is `JWT`, not `Bearer` (`SIMPLE_JWT["AUTH_HEADER_TYPES"]`).
- `DJOSER["TOKEN_MODEL"]` is `None` because the project is JWT-only and `rest_framework.authtoken` is not installed; without it Djoser's `DELETE /auth/users/me/` crashes trying to delete a DRF token.
- Djoser serializers are overridden through the `DJOSER["SERIALIZERS"]` setting. `core.serializers.UserCreateSerializer` extends the registration payload with `first_name` / `last_name` and a required, write-only `phone_number`. `core.serializers.CurrentUserSerializer` adds `first_name` / `last_name` (editable with `PUT`/`PATCH`) and a read-only `phone_number` to `/auth/users/me/`; `username` stays read-only there. To change other Djoser payloads, subclass the Djoser serializer in `core/serializers.py` and register it in that setting rather than writing a new view.
- `core.admin.UserAdmin` extends the stock `UserAdmin` add form with email and name fields, since email is required to be unique, and shows the user's `Student` inline.

#### Student profile

- `classes.Student` is the profile of a registered student: a one-to-one to `settings.AUTH_USER_MODEL` (`related_name="student"`, deleted with the user) plus a required `phone_number` (optional `+`, 7–15 digits, not unique). It lives in `classes`, not `core`, because a class cannot exist without a student. It is registered in `classes/admin.py`.
- A Student is created by a `post_save` signal on the user model: the handler is `core.signals.create_student`, connected in `CoreConfig.ready()`. It creates a Student only for a newly created user that carries a `_phone_number` attribute (named by `core.signals.PHONE_NUMBER_ATTR`, which the serializer imports).
- Only registration sets that attribute. `UserCreateSerializer.validate()` takes `phone_number` out of the attrs while Djoser validates the password (Djoser builds `User(**attrs)`), and `perform_create()` builds the user itself instead of calling `create_user()`, attaches `_phone_number`, and saves inside `transaction.atomic()`. The signal runs inside that transaction, so if the Student cannot be created the user is not created either.
- Users created by `createsuperuser` or in the Django admin have no phone number and get no Student, so never assume `user.student` exists: `/auth/users/me/` returns `phone_number: null` for them. An admin can add a Student through the inline on the User page.
- `phone_number` cannot be changed through `/auth/users/me/`; it is edited in the Django admin.

`REST_FRAMEWORK` sets only the default authentication class (JWT). No default permission class is set, so DRF's `AllowAny` default applies — new views must declare their own `permission_classes`.

`REST_FRAMEWORK` also sets one default throttle class, `core.throttling.PasswordResetThrottle` (see Password reset); it lets every other route through, so a new view needs no throttle setting.

Email goes through Django 6.1's `MAILERS` setting, not the deprecated `EMAIL_BACKEND` / `EMAIL_HOST` settings. When `EMAIL_HOST` is set in `.env` the default mailer is SMTP, configured from the `EMAIL_*` variables; when it is not set the console backend is used, so Djoser emails (password reset, password changed) print to the dev server's stdout. `DEFAULT_FROM_EMAIL` comes from `.env` too; when it is empty the sender is `Science Nest <webmaster@localhost>`.

#### Password reset

Password reset is Djoser's `reset_password` and `reset_password_confirm` actions, configured in `config/settings.py`; there is no view, serializer or template of our own (the emails use Djoser's stock templates).

- `DJOSER["PASSWORD_RESET_CONFIRM_URL"]` is `reset-password/{uid}/{token}`. Djoser has no default for it: without it `reset_password` crashes with a 500 for a registered email.
- `DJOSER["EMAIL_FRONTEND_DOMAIN"]` / `["EMAIL_FRONTEND_PROTOCOL"]` come from `FRONTEND_DOMAIN` / `FRONTEND_PROTOCOL` in `.env` (default `localhost:3000`, `http`), so the link opens the frontend. Without them Djoser would use the API's own host. `EMAIL_FRONTEND_SITE_NAME` ("Science Nest") is the name used in the emails.
- `DJOSER["PASSWORD_CHANGED_EMAIL_CONFIRMATION"]` sends the "password changed" email after a reset and after `set_password`.
- `PASSWORD_RESET_TIMEOUT` (one hour) is how long a link is valid. A link is single-use because the token is tied to the password hash and `last_login`, and Djoser updates both on confirm.
- `SIMPLE_JWT["CHECK_REVOKE_TOKEN"]` puts a hash of the user's password in every token and rejects an access token whose hash no longer matches. SimpleJWT does not make that check on `/auth/jwt/refresh/`, so `core.serializers.TokenRefreshSerializer` (registered as `SIMPLE_JWT["TOKEN_REFRESH_SERIALIZER"]`) makes it for refresh tokens. Together they log a user out everywhere after a password change. `/auth/jwt/verify/` only checks a token's signature and expiry, not the password hash.
- `core.throttling.PasswordResetThrottle` limits `reset_password` to `DEFAULT_THROTTLE_RATES["password_reset"]` (5/hour) per IP address, for anonymous and logged-in callers alike. Djoser's `UserViewSet` cannot be given a throttle without subclassing the view, so the class is a DRF default that returns early for every other action and view. Its counter is in Django's default cache, which is in-memory and per process: with several workers the limit is per worker until a shared cache is configured, and behind a proxy `REST_FRAMEWORK["NUM_PROXIES"]` must be set for the real client IP to be used.
- `reset_username` has the same missing-URL crash (`USERNAME_RESET_CONFIRM_URL` is not set); it is not part of this feature.

### Admin timezone

The database and the API are UTC; the Django admin shows and accepts Asia/Karachi (PKT). Nothing about this is stored: there is no schema change behind it.

- `ADMIN_TIME_ZONE = "Asia/Karachi"` in `config/settings.py` names the admin's timezone. `TIME_ZONE` stays `"UTC"`.
- `core.middleware.AdminTimezoneMiddleware` (last in `MIDDLEWARE`) wraps every request whose path starts with the admin URL prefix (`reverse("admin:index")`) in `timezone.override(...)` and does nothing for any other request, so API responses, including the browsable API, stay UTC.
- With that timezone active Django converts datetimes in the admin itself: a trial lesson's `starts_at` is listed, entered and filtered in PKT and saved as UTC.
- A weekly class's `day` + `time` is not a datetime, so Django cannot convert it. `slot_in_zone(day, time, tz)` (UTC to a timezone) and `slot_to_utc(day, time, tz)` (back) in `classes/timeslots.py` do it, rolling the day over and wrapping the week (Monday 21:00 UTC is Tuesday 02:00 PKT; Monday 03:00 PKT is Sunday 22:00 UTC). They move the whole time, hours and minutes, by the zone's own offset, so :30 and :45 offsets work; nothing hard-codes +5. A weekly slot has no date, so the offset is the one in effect at an optional `at` moment (now by default; `utc_offset_minutes(tz, at)`, also taken by `with_week_minute`): a zone with daylight saving converts correctly for a given date, and a round trip always gives back the original slot.
- `classes/admin.py` uses them for weekly classes: `WeeklyClassAdminForm` opens a class in PKT and converts what the admin typed to UTC in `clean()`, before model validation, so the full-hour, clash and trial lesson rules run on the UTC values; the list shows "Day (PKT)" and "Time (PKT)" columns; `WeeklyClassQuerySet.with_week_minute(tz)` (`classes/querysets.py`) annotates the minute of the week in that timezone, which the list is ordered by and `WeeklyClassDayFilter` filters on.
- `WeeklyClass.__str__` and `TrialLesson.__str__` use the active timezone, so a booking's name reads in PKT inside the admin and in UTC everywhere else.
- `TrialLessonAdmin` has no `date_hierarchy`: outside UTC it needs MySQL's timezone tables, which are not loaded (see Environment). It has a `starts_at` date filter instead.

## Claude Code tooling

Commands (`.claude/commands/`):

- `/create-spec <feature>` — creates the feature branch and writes `.claude/specs/<NN>-<feature>.md`. Writes no application code.
- `/test-feature <feature>` — runs `nest-test-writer`, then `nest-test-runner`. Fixes nothing.
- `/code-review-feature <feature>` — runs both reviewers in parallel and merges their reports. Edits files only after the user approves the action plan.

Agents (`.claude/agents/`):

- `nest-test-writer` — writes tests from the spec. It may only touch `<app>/tests/` and the root `conftest.py`, and keeps its own project memory under `.claude/agent-memory/`.
- `nest-test-runner` — runs one test file and classifies each failure as an implementation bug, a test bug or an environment problem. Read-only.
- `nest-security-reviewer` — reviews changed code for permissions, queryset scoping, serializer exposure and rule bypasses. Read-only.
- `nest-quality-reviewer` — reviews changed code for project conventions, Django and DRF idioms and spec conformance. Read-only.

The command and agent files refer to this file by heading name and requirement number ("Product requirements 4", "API conventions", "Architecture > Auth", "Implemented vs Stub Routes") and carry their own copies of the booking rules and the feature table. When a product requirement, an API convention, a heading or a feature name changes here, update those files in the same change.

## Implemented vs Stub Routes

Keep this section current: whenever a route is added, removed, renamed, or goes from Stub to Implemented, update the tables in the same change. `/test-feature` and `/code-review-feature` read these tables and stop while a feature's routes are still marked Stub.

- **Implemented** — the route is registered in the URLconf and works.
- **Stub** — planned from the product requirements, no code yet. Stub paths are proposals and may change when built.

Only student-facing routes are listed. `admin/` (Django admin site) is not part of the API. Djoser also registers `GET /auth/users/` and `GET`/`PUT`/`PATCH`/`DELETE /auth/users/{id}/`; they are left out because managing other users is admin work, and students use `/auth/users/me/`.

### Auth (Djoser + SimpleJWT, mounted in `config/urls.py`)

| Method | Path | Status |
| --- | --- | --- |
| POST | `/auth/users/` | Implemented |
| GET | `/auth/users/me/` | Implemented |
| PUT | `/auth/users/me/` | Implemented |
| PATCH | `/auth/users/me/` | Implemented |
| DELETE | `/auth/users/me/` | Implemented |
| POST | `/auth/users/activation/` | Implemented |
| POST | `/auth/users/resend_activation/` | Implemented |
| POST | `/auth/users/set_password/` | Implemented |
| POST | `/auth/users/reset_password/` | Implemented |
| POST | `/auth/users/reset_password_confirm/` | Implemented |
| POST | `/auth/users/set_username/` | Implemented |
| POST | `/auth/users/reset_username/` | Implemented |
| POST | `/auth/users/reset_username_confirm/` | Implemented |
| POST | `/auth/jwt/create/` | Implemented |
| POST | `/auth/jwt/refresh/` | Implemented |
| POST | `/auth/jwt/verify/` | Implemented |

### Subjects

Read-only by design; subjects are managed in the Django admin. Both routes are public.

| Method | Path | Status |
| --- | --- | --- |
| GET | `/subjects/` | Implemented |
| GET | `/subjects/{slug}/` | Implemented |

### Weekly classes

| Method | Path | Status |
| --- | --- | --- |
| GET | `/classes/` | Implemented |
| POST | `/classes/` | Implemented |
| GET | `/classes/{id}/` | Implemented |
| PUT | `/classes/{id}/` | Implemented |
| PATCH | `/classes/{id}/` | Implemented |
| DELETE | `/classes/{id}/` | Implemented |

### Trial lessons

| Method | Path | Status |
| --- | --- | --- |
| GET | `/trial-lessons/` | Implemented |
| POST | `/trial-lessons/` | Implemented |
| GET | `/trial-lessons/{id}/` | Implemented |
| PUT | `/trial-lessons/{id}/` | Implemented |
| PATCH | `/trial-lessons/{id}/` | Implemented |
| DELETE | `/trial-lessons/{id}/` | Implemented |

### My schedule

| Method | Path | Status |
| --- | --- | --- |
| GET | `/schedule/` | Implemented |

### Slots availability

| Method | Path | Status |
| --- | --- | --- |
| GET | `/availability/` | Implemented |
