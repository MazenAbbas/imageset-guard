# External user-testing protocol (pending)

**Status: this protocol has not been executed.** No external user feedback
has been collected for this project at any point. This document exists so
that when it is executed, it is executed consistently -- it is not itself
evidence of usability.

## Purpose

Determine whether ImageSet Guard is genuinely usable, in its target
workflows, by people who did not build it -- and surface friction points
that automated tests cannot, by construction (CLI wording clarity, whether
error messages actually help someone unblock themselves, whether the
terminal output's information density is right for a first-time user).

## Participants (5, minimum for this round)

1. Two students, unfamiliar with the tool, each with their own small local
   image dataset (their own coursework/project data, not provided by us).
2. One data scientist or ML engineer with an existing dataset they already
   work with.
3. One data engineer or CI maintainer evaluating it as a pipeline gate.
4. One instructor, if available (optional for the first round).

## Privacy boundary (must hold for every session)

- Participants run the tool **on their own machine, on their own data**.
  Their dataset, its file names, and its content are never sent to us,
  screen-shared, or uploaded anywhere -- this is a direct consequence of
  the tool being local-only and read-only, not an extra precaution we ask
  of participants.
- Only the participant's own typed observations and answers to the
  questions below are collected.
- No participant is asked to run the tool on anyone else's data or on a
  dataset they are not authorized to scan.

## Tasks

For each participant, in order, timed loosely (not a speed test):

1. Install the released wheel in a fresh virtual environment.
2. Run `imageset-guard doctor`. Ask: did the output tell you whether your
   environment was ready?
3. Run `imageset-guard example ./demo` then `imageset-guard scan ./demo`
   with no prior explanation beyond `--help`. Ask: could you tell what
   happened and why, from the output alone?
4. Run `imageset-guard scan` on the participant's own dataset (their
   choice of layout flag, with `--help` available). Ask: did any finding
   confuse you? Was the suggested remediation actually something you could
   act on?
5. (Data engineer only) Write a `policy.toml` with at least one limit from
   [docs/guides.md](guides.md) and run `imageset-guard policy-check` then
   `scan --config`. Ask: was the error message clear when you got the
   policy wrong the first time?
6. Ask the participant to describe, in their own words, what a `PASS`
   result does and does not mean.

## Success criteria

- The participant completes tasks 1-4 without needing help beyond `--help`
  and the README.
- The participant's own description in task 6 does not overstate what
  `PASS` means (no claim of "the dataset is definitely fine/unbiased/
  correct").
- No participant reports a finding's remediation text as actionable-sounding but actually unclear once they tried to follow it.

## Observation questions (recorded verbatim, not paraphrased)

- Where did you hesitate or re-read something?
- What did you expect to happen that didn't?
- Was there a moment you weren't sure if the tool had actually done
  anything?
- Would you add this to a workflow you already have? Why or why not?

## Feedback form (per participant)

- Role (student / data scientist / ML engineer / data engineer / instructor)
- Dataset size and rough shape (splits? how many classes? roughly how many
  images?) -- no file names, paths, or content
- Answers to the observation questions above
- Anything they tried that didn't work as expected
- One thing they would change

## After execution

Results should be summarized (not the raw dataset descriptions) in a
follow-up note, and this file's status line updated to name the date range
and number of participants actually run. Until that happens, every claim
in this project's documentation about usability is based on the
maintainer's own testing and the executable acceptance scenarios in
`tests/test_acceptance_scenarios.py`, not on independent user feedback.
