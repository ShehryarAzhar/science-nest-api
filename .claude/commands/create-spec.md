---
description: Create a spec file and feature branch for a Science Nest API feature. Pass a feature name e.g. /create-spec trial-lessons
argument-hint: users | subjects | weekly-classes | trial-lessons | schedule | slots-availability | <number> <feature name>
allowed-tools: Read, Write, Glob, Grep, Bash(git:*)
---

You are a senior developer spinning up a new feature for the
Science Nest API. Always follow the rules in CLAUDE.md.

User input: $ARGUMENTS

## Step 1 — Check working directory is clean
Run `git status` and check for uncommitted, unstaged, or
untracked files. If any exist, stop immediately and tell
the user to commit or stash changes before proceeding.
DO NOT CONTINUE until the working directory is clean.

## Step 2 — Parse the arguments
If $ARGUMENTS is one of the known features, take the values
from this table:

| Feature | `step_number` | `feature_title` | Spec source in `CLAUDE.md` | Routes |
| --- | --- | --- | --- | --- |
| `users` | 01 | Users and Student Profile | Product requirements 1 (Users) and Architecture > Auth | `/auth/users/`, `/auth/users/me/`, `/auth/jwt/create/` |
| `subjects` | 02 | Subjects | Product requirements 2 | `/subjects/` |
| `weekly-classes` | 03 | Weekly Class Scheduling | Product requirements 3 | `/classes/` |
| `trial-lessons` | 04 | Trial Lessons | Product requirements 4 | `/trial-lessons/` |
| `schedule` | 05 | My Schedule | Product requirements 5 | `/schedule/` |
| `slots-availability` | 06 | Slots Availability | Product requirements 6 | `/availability/` |

Otherwise expect `<number> <feature name>` (e.g. `6 class
cancellation`) and extract:

1. `step_number` — zero-padded to 2 digits: 6 → 06, 11 → 11
2. `feature_title` — human readable title in Title Case
3. `feature_slug` — lowercase kebab-case, only a-z, 0-9
   and -, maximum 40 characters

For known features `feature_slug` is the feature name.
In both cases `branch_name` is `feature/<feature_slug>`.

If you cannot infer these from $ARGUMENTS, ask the user
to clarify before proceeding.

## Step 3 — Check branch name is not taken
Run `git branch -a` to list existing branches.
If `branch_name` is already taken, append a number:
`feature/trial-lessons-01`, `feature/trial-lessons-02` etc.

## Step 4 — Switch to main and pull latest
Run:
```
git checkout main
git pull origin main
```

## Step 5 — Create and switch to the feature branch
Run:
```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase
Read these before writing the spec:
- `CLAUDE.md` — product requirements, API conventions,
  architecture, route tables
- `config/settings.py` and `config/urls.py` — installed
  apps, DRF settings, mounted routes
- `pyproject.toml` — installed dependencies
- In `classes/` and `core/`, whichever of these exist:
  `models.py`, `constants.py`, `validators.py`,
  `timeslots.py`, `querysets.py`, `rules.py`,
  `serializers.py`, `views.py`, `urls.py`,
  `admin.py`, and the files in `migrations/`
- All files in `.claude/specs/` — avoid duplicating
  existing specs and pick up any rule an earlier spec
  deferred to this feature

Check the "Implemented vs Stub Routes" section of
`CLAUDE.md`. If every route of the requested feature is
already marked Implemented, warn the user and stop.

## Step 7 — Write the spec
Base the spec on the feature's section of `CLAUDE.md`. Do
not invent behaviour that is not there. If a requirement is
ambiguous (e.g. which status code a locked trial lesson
returns), ask the user before writing it down.

Generate a spec document with this exact structure:

---
# Spec: <feature_title>

## Overview
One paragraph describing what this feature does and why
it is being built at this point.

## Depends on
Which features and specs must already be implemented.
If none: state "No dependencies".

## Requirements
Numbered list of every rule from the feature's section of
`CLAUDE.md` that this spec implements, in its own words but
without changing the meaning.

## Deferred rules
Rules of this feature that cannot be implemented yet
because they depend on a model that does not exist (e.g.
the trial lesson clash check before trial lessons exist),
and which spec must pick them up. Also list any rule an
earlier spec deferred to this one.
If none: state "No deferred rules".

## Routes
Every new route:
- `METHOD /path` — description — access level
  (public / authenticated student)

If no new routes: state "No new routes".

## Models and database changes
Each new or changed model with its fields, field types,
choices, foreign keys and `on_delete`, and every database
constraint (`UniqueConstraint`, `CheckConstraint`).
State that a migration is generated with `makemigrations`.
Always verify against the existing `models.py` and
migrations before writing this.
If none: state "No database changes".

## Serializers and validation
Each serializer, its fields, which are read-only, and each
validation rule with where it is enforced (serializer
`validate`, model constraint, or both) and the error it
returns.

## Views and URLs
Each view or viewset, its base class, `permission_classes`,
how `get_queryset` is scoped, and how it is registered on
the router and mounted in `config/urls.py`.

## Admin
Each model registered in `admin.py` and anything that is
admin-only (e.g. marking a trial lesson completed).

## Files to change
Every existing file that will be modified, including
`CLAUDE.md` for the route tables.

## Files to create
Every new file that will be created.

## New dependencies
Any new packages, added with `uv add`.
If none: state "No new dependencies".

## Rules for implementation
Specific constraints Claude must follow. Always include:
- Money is stored in `DecimalField`, never `FloatField`
- Reference the user via `settings.AUTH_USER_MODEL` /
  `get_user_model()`, never `django.contrib.auth.models.User`
- Every view declares its own `permission_classes`; no
  default permission class is set
- Booking querysets are scoped to `request.user`; timeslot
  clash checks look at every user's bookings
- Booking rules are enforced on the server in
  serializers/models, backed by a database constraint
  where possible
- Prefer `ModelViewSet` on a DRF router; subjects use
  `ReadOnlyModelViewSet`
- No teacher- or admin-facing endpoints; register every
  model in `admin.py` instead
- No templates or server-rendered pages
- Update the "Implemented vs Stub Routes" tables in
  `CLAUDE.md` in the same change

Add any rule specific to this feature.

## Tests
The test file the feature will be covered by (e.g.
`classes/tests/test_trial_lessons.py`) and the behaviours
it must cover. Tests are written and run afterwards with
`/test-feature`, not as part of implementation.

## Definition of done
A specific testable checklist. Each item must be
verifiable by a request to the API, an action in the
Django admin, or a command. Always include:
- [ ] `uv run python manage.py makemigrations --check`
      reports no missing migrations
- [ ] Each route returns the expected status for an
      anonymous request
- [ ] The feature's routes are marked Implemented in
      `CLAUDE.md`
---

## Step 8 — Save the spec
Save to: `.claude/specs/<step_number>-<feature_slug>.md`

## Step 9 — Report to the user
Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<step_number>-<feature_slug>.md
Title:     <feature_title>
```

Then tell the user:
"Review the spec at `.claude/specs/<step_number>-<feature_slug>.md`
then enter Plan Mode with Shift+Tab twice to begin implementation.
Once it is implemented, run `/test-feature <feature_slug>`."

Do not print the full spec in chat unless explicitly asked.
