---
description: Runs parallel security and quality code review for a specific Science Nest API feature. Pass the feature name as argument e.g. /code-review-feature trial-lessons
argument-hint: subjects | weekly-classes | trial-lessons | schedule | slots-availability | users
allowed-tools: Bash(git diff:*), Bash(git status:*)
---

Run the full code review pipeline for the feature
specified in $ARGUMENTS.

If no argument is provided, stop immediately and say:
"Please provide a feature name. Usage:
/code-review-feature <feature> e.g. /code-review-feature
trial-lessons. Features: subjects, weekly-classes,
trial-lessons, schedule, slots-availability, users"

Look the feature up in this table:

| Feature | Spec file | Spec in `CLAUDE.md` | Routes | App |
| --- | --- | --- | --- | --- |
| `users` | `.claude/specs/01-users.md` | Product requirements 1 (Users) and Architecture > Auth | `/auth/users/`, `/auth/users/me/`, `/auth/jwt/create/` | `core` |
| `subjects` | `.claude/specs/02-subjects.md` | Product requirements 2 (Subjects) | `/subjects/` | `classes` |
| `weekly-classes` | `.claude/specs/03-weekly-classes.md` | Product requirements 3 (Weekly class scheduling) | `/classes/` | `classes` |
| `trial-lessons` | `.claude/specs/04-trial-lessons.md` | Product requirements 4 (Trial lessons) | `/trial-lessons/` | `classes` |
| `schedule` | `.claude/specs/05-schedule.md` | Product requirements 5 (My schedule) | `/schedule/` | `classes` |
| `slots-availability` | `.claude/specs/06-slots-availability.md` | Product requirements 6 (Slots availability) | `/availability/` | `classes` |

If $ARGUMENTS is not one of these features, stop
immediately and say:
"Unknown feature '$ARGUMENTS'. Features: subjects,
weekly-classes, trial-lessons, schedule, slots-availability, users"

In the steps below, `<app>` and `<spec file>` mean the
values from the feature's row in the table.

`users` also covers the `Student` profile, whose model
lives in the `classes` app: for `users`, add
`classes/models.py`, `classes/constants.py`,
`classes/validators.py`, `classes/admin.py`,
`classes/migrations/` and `core/signals.py` to the
source files listed in the steps below.

---

## Pre-flight Check

Before invoking any subagents:

1. If the feature's routes are still marked Stub in the
   "Implemented vs Stub Routes" section of `CLAUDE.md`,
   stop immediately and say:
   "The $ARGUMENTS routes are still marked Stub in
   CLAUDE.md. Implement the feature (and update the route
   tables) before reviewing it."

2. Collect the changes:
   - Run `git diff main...HEAD` for changes committed on
     the feature branch
   - Run `git diff HEAD` for staged and unstaged changes
   - Run `git status --porcelain --untracked-files=all`
     for untracked files, which `git diff` does not show

3. If all three are empty, stop immediately and say:
   "No changes detected. Implement the feature before
   running code review."

4. Build two lists from the output: the changed files and
   the untracked files. Leave out anything under
   `<app>/tests/` and the root `conftest.py`; tests are
   reviewed by the test agents, not here.

Spec files are written by `/create-spec`. If the
feature's spec file is "none" or does not exist, tell
both subagents that there is no spec file and that the
feature's section of `CLAUDE.md` is the whole spec, and
say so in the final report.

---

## Step 1: Parallel Review

Invoke both subagents simultaneously, in a single
message, with the same context:

**nest-security-reviewer** receives:
- Feature under review: $ARGUMENTS
- Spec for context: `<spec file>`, together with the
  feature's section of `CLAUDE.md`, its "API
  conventions" section and the feature's route table
- The list of changed files and the list of untracked
  files from the pre-flight check
- Diff commands to run: `git diff main...HEAD` and
  `git diff HEAD`. Untracked files must be read in full
- Source files to reference: `<app>/models.py` (and for
  `classes` the modules beside it: `constants.py`,
  `validators.py`, `timeslots.py`, `querysets.py`,
  `rules.py`),
  `<app>/serializers.py`, `<app>/views.py`,
  `<app>/urls.py`, `config/urls.py` and
  `config/settings.py`
- Instruction: Review only the changed code for
  security problems. Do not comment on quality or
  style. Do not report a rule `<spec file>` defers to a
  later spec.

**nest-quality-reviewer** receives:
- Feature under review: $ARGUMENTS
- Spec for context: `<spec file>`, together with the
  feature's section of `CLAUDE.md`, its "API
  conventions" section and the feature's route table
- The list of changed files and the list of untracked
  files from the pre-flight check
- Diff commands to run: `git diff main...HEAD` and
  `git diff HEAD`. Untracked files must be read in full
- Source files to reference: `<app>/models.py` (and for
  `classes` the modules beside it: `constants.py`,
  `validators.py`, `timeslots.py`, `querysets.py`,
  `rules.py`),
  `<app>/serializers.py`, `<app>/views.py`,
  `<app>/urls.py`, `<app>/admin.py`,
  `<app>/migrations/`, `config/urls.py` and `CLAUDE.md`
- Instruction: Review only the changed code for
  quality, project conventions, Django and DRF idioms
  and conformance to the spec. Do not comment on
  security concerns. Do not report a rule `<spec file>`
  defers to a later spec.

Both subagents must run in parallel. Do not wait for
one to finish before starting the other.

---

## Step 2: Unified Report

Once both subagents have completed, combine their
findings into a single unified report. De-duplicate
overlapping findings: if both agents flagged the same
line, merge them into one finding with both
perspectives noted and keep the higher severity.

Structure the combined report as:

### Code Review Report — $ARGUMENTS

**Security Findings**
- Mirror the nest-security-reviewer's findings,
  each with its severity and `file:line`

**Quality Findings**
- Mirror the nest-quality-reviewer's findings,
  each with its severity and `file:line`

**Combined Action Plan**
An ordered checklist of everything to fix, prioritized
by severity:
1. Critical and High security findings
2. High quality findings
3. Medium and Low security findings
4. Medium and Low quality findings

Each item names the file and line and the fix in one
line. Minor notes are listed after the checklist and
are not part of it.

**Overall Verdict**
One of:
- ✅ APPROVED — no findings, ready to commit
- ⚠️ APPROVED WITH SUGGESTIONS — only Medium or Low
  findings; can commit, address them in a later step
- ❌ CHANGES REQUESTED — at least one Critical or High
  finding; fix before committing, see the action plan

---

## Step 3: Ask for Approval

If the action plan is empty, stop after the report.

Otherwise, after presenting the unified report, ask:

"Do you want me to implement the action plan now?"

Wait for explicit user confirmation before making
any changes. Do not touch any files until the user
approves.

After implementing an approved action plan, tell the
user:
"Run `/test-feature $ARGUMENTS` to confirm the fixes
did not break the feature."

---

## Rules

- Do NOT edit any files before user approval
- Do NOT start one reviewer before the other — both
  must run in parallel
- Do NOT skip the pre-flight check
- Do NOT review or change files under `<app>/tests/`
  or the root `conftest.py`
- Do NOT add findings of your own to the reviewers'
  reports; only merge, de-duplicate and order them
- If a reviewer reports a contradiction between
  `<spec file>` and `CLAUDE.md`, put it at the top of
  the report and ask the user to resolve it
- If either subagent fails or returns no output,
  report it and do not present a partial review as
  complete
