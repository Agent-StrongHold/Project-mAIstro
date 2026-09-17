---
id: SPEC-091726-7c2a
title: "A requirements interview precedes every Goal and CreativeBrief commit"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-17
accepted: 2026-09-17
history:
  - status: Proposed
    date: 2026-09-17
  - status: Accepted
    date: 2026-09-17
  - status: AC Defined
    date: 2026-09-17
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-060
implements: []
related:
  - maistro-engine#SPEC-192
  - maistro-engine#SPEC-160
  - maistro-engine#ADR-091626-ba4f
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/agents/test_brief_interview.py
source:
  - packages/maistro-core/src/maistro/agents/brief_interview.py
ac-modules:
  AC-1: maistro.agents.brief_interview
  AC-2: maistro.agents.brief_interview
  AC-3: maistro.agents.brief_interview
  AC-4: maistro.agents.brief_interview
  AC-5: maistro.agents.brief_interview
  AC-6: maistro.agents.brief_interview
  AC-7: maistro.agents.brief_interview
  AC-8: maistro.agents.brief_interview
  AC-9: maistro.agents.brief_interview
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-091726-7c2a: A requirements interview precedes every Goal and CreativeBrief commit

- **Status:** AC Defined
- **Date:** 2026-09-17
- **Issues:** #774 (CreativeBrief), #804 (persistent Workspace Agent), #53 (Workspace Agent chat), #458 (canonical Goal)
- **Technical Area:** Workspace Agent intake, Design Studio briefs

## Purpose

When a person tells the persistent Workspace Agent to make something ("let's
make a new video, let's start drafting a storyboard"), the agent must not mint
a Goal from that sentence. A Goal is a desired state with a success condition
and a stop condition (`docs/architecture/INTEROP-ONTOLOGY-v1.md`, #458), and a
CreativeBrief adds "audience, constraints, source truth, acceptance
interpretation, requested deliverables, and creative guidance"
(`docs/product/DESIGN-STUDIO.md`, #774). A wish carries none of that. The
missing material has to be drawn out of the person in conversation, and only
then committed.

This spec defines that conversation as a deterministic state machine in
`maistro.agents.brief_interview`, so the behaviour is the same on every run
and can be tested without a model. It is the conversational counterpart of
ADR-061's discovery form: the form's fields, asked one at a time in plain
words, with the record answering what it can and the person answering the
rest.

## Why a conversation and not a form

ADR-061 introduced discovery forms because "structured upfront input
eliminates redirect loops". SPEC-192 §Stage 1 then chose a one-question-at-a-
time interview over a form for persona authoring, because a form asks
everything at once whether or not the record already knows it, and a person
in chat answers in sentences, not fields. The same holds here, with three
additions that a form cannot express:

1. **The record answers first.** If the workspace already holds the source
   footage for the subject the person named, the agent says so and does not
   ask. A question the record can answer is a question the agent should not
   ask (`docs/product/DESIGN-STUDIO.md`, "Runtime is in charge").
2. **A default is allowed only where it is defensible.** "You decide" on the
   channel takes the persona's usual channel and says so; "you decide" on the
   subject is refused, because there is no defensible default for what a
   video is about.
3. **Nothing is written until commit.** The interview is chat state. No Goal,
   no CreativeBrief, no Run exists until the person confirms the summary, so
   "never mind" has nothing to undo.

## The interview

A `BriefScript` is an ordered tuple of `BriefField`s. A field is required or
optional, may carry recognised options (each with match patterns and a plain
value), may carry a default for "you decide", and may name a `record_key`
under which the workspace record can answer it. The first script,
`VIDEO_BRIEF_SCRIPT`, has five required fields (subject, outcome, channel,
source, deadline) and three optional ones (voice, claims, control mode).

`BriefInterview` is the conversation so far: the opening turn, the answers
keyed by field with the **source** of each (`user`, `verbatim`, `record`,
`assumed`), notes, and the transcript. Updates are immutable copies, as with
`ProgramContext`.

One turn goes through `apply_brief_answer`, in this order:

| The person says | The interview does | Event |
|---|---|---|
| "never mind", "cancel" | marks the interview dropped; nothing was ever written | `dropped` |
| "change *field* to *x*" | re-answers any field, open or not; "change *field*" alone reopens it | `changed` |
| anything, once every required field is known | sets a matching optional field, else records a note on the brief (never a Goal change) | `answered` / `noted` |
| "you decide", "skip" | takes the current field's default marked `assumed`, or refuses when the field has none | `assumed` / `cannot_assume` |
| something that fits the current field | records it as `user` | `answered` |
| something that fits a *different* open required field | records it there; the current question stands | `routed` |
| anything else | carries it `verbatim` | `answered` |

`start_brief_interview` reads the opening turn for answers first, so "a reel
about the grouting haze, before the market" is not asked which channel or
when. `fill_from_record` answers from the record and can be re-run as the
record learns more; it never overrides an answer the person gave.

`brief_summary` is the "brief so far" a surface shows beside the chat: every
field with its value and source, open required fields marked `open`,
unanswered optional fields showing the default they will take.

`commit_brief` is the gate. It returns the draft a Goal revision and a
CreativeBrief version are written from: the field values, the source of
each, the list of assumed fields, the notes and the opening turn. It raises
`BriefIncompleteError` naming the missing fields otherwise. Nothing upstream
may mint a Goal from an interview this function would not commit.

## What this spec does not do

- It does not define `Goal`, `CreativeBrief` or their stores. Those remain
  #458 and #774; `maistro.goals` is the declared owner in the interop
  contract and does not exist yet. This spec produces the draft they will be
  written from, and refuses to produce it early.
- It does not call a model. A caller may paraphrase the questions with one;
  the fields, the routing and the gate are here.
- It does not change the onboarding interview in
  `maistro.agents.program_context`. That one asks what a workspace is; this
  one asks what a piece of work is. They share `InterviewTurn` and nothing
  else.
- It does not add a route. The Workspace Agent chat that would host it is
  #53 / M3-D; the demo of the interaction lives in the Content Studio
  artifact referenced from ADR-091626-ba4f.

## Acceptance Criteria

```gherkin
Feature: A requirements interview precedes every Goal and CreativeBrief commit

  @AC-1
  Scenario: A work request opens an interview and nothing is committable yet
    Given a person says "let's make a new video, let's start drafting a storyboard"
    When the interview is started from that turn
    Then every required field is missing
    And a commit is refused naming every missing field
    And the opening turn is the first line of the transcript

  @AC-2
  Scenario: One required question at a time, in script order
    Given an interview with no answers
    When the person answers each question as it is asked
    Then the questions come in the script's order
    And no optional field is ever asked as a gate
    And the brief so far shows each field as known, open or assumed with its source

  @AC-3
  Scenario: Answers in the opening turn or the record are not asked
    Given an opening turn that names a channel and a deadline
    And a record that knows the source footage
    When the interview is started
    Then channel and deadline are recorded from the person
    And source is recorded from the record
    And only subject and outcome remain to ask
    And a later record fill never overrides an answer the person gave

  @AC-4
  Scenario: Free text is matched to an option or carried verbatim
    Given the interview is asking about the subject
    When the person answers in a sentence that matches no option
    Then the answer is carried verbatim
    When the person answers the outcome question with "teach people the wipe"
    Then the outcome is recorded as the matching option

  @AC-5
  Scenario: An answer that fits another open field goes there and the question stands
    Given the interview is asking about the channel
    When the person says "after the market"
    Then the deadline is recorded
    And the channel is still open
    And the channel question is asked again

  @AC-6
  Scenario: "You decide" takes a marked default and is refused where none is defensible
    Given the interview is asking about the subject
    When the person says "you decide"
    Then the interview refuses and the subject stays open
    Given the interview is asking about the outcome
    When the person says "up to you"
    Then the outcome takes its default marked assumed

  @AC-7
  Scenario: "Change" re-answers any field and "never mind" drops with nothing written
    Given every required field is known
    When the person says "change channel to youtube"
    Then the channel is re-answered
    When the person says "change the deadline"
    Then the deadline is reopened and asked again
    When the person says "never mind"
    Then the interview is dropped
    And a commit is refused
    And further turns are ignored

  @AC-8
  Scenario: Commit only when every required field is known, and the draft says what was assumed
    Given four of five required fields are known
    When a commit is attempted
    Then it is refused naming the missing field
    When the fifth is assumed and a commit is attempted
    Then the draft carries every field value with its source
    And the draft lists the assumed fields including unanswered optional ones
    And the draft counts the opening turn and every answer

  @AC-9
  Scenario: Once required fields are known, extra turns set optional fields or become notes
    Given every required field is known
    When the person says "I want to mark it up"
    Then the control mode is recorded from the person
    When the person says "keep the intro under three seconds"
    Then it is recorded as a note on the brief
    And the committed draft carries the note
```

## Rollout

`maistro.agents.brief_interview` ships with `VIDEO_BRIEF_SCRIPT` as the first
script. Persona-declared scripts (a `briefs:` block beside
`PersonaTemplate.interview`) and the Workspace Agent chat route that hosts
the interview are follow-ups under #53 and #774; this spec's gate is what
they call.
