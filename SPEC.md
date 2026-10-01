# Glitch Loom specification

*Weave topics into learning journeys.*

Status: working draft, updated 29 Sep 2026 (version 0.5.2). The interface is **not frozen**. The owner judges the visual direction. Where this document and `CHECKLIST.md` differ, the checklist is current.

This document describes what Loom does today. Where something is planned and not built, it says so.

## 1. What Loom is

An internal tool for the Glitch team to research, design, review and finalise courses, workshops, cohort programmes, talks and clinics.

| Boundary | Rule |
|---|---|
| Who uses it | The Glitch team only |
| Learners | Never use Loom. They use the Glitch website, a separate product |
| Not in Loom | Student accounts, enrollment, payments, a learner portal, public publishing |
| Glitch website | Not connected. Not modified by this project |
| Earlier curriculum apps | Nothing is reused from them. They are comparison baselines only |
| Where it runs | On one computer, at `http://127.0.0.1:8790`. It answers only to its own page: requests naming another host or coming from another site are refused, for pages and data alike. Each connection carries one request |

## 2. Requirements

| # | Loom must | How it is met today |
|---|---|---|
| R1 | Work across any subject | Questions and prompts name no subject. Topics are whatever the team types |
| R2 | Join topics only when it is justified | Each session states what every topic contributes. Weak or unjustified joins are flagged |
| R3 | Teach missing foundations | Starting point is asked. Prerequisites and support are written for every session |
| R4 | Let the outcome drive the course | The outline works backwards from the requested outcome. See section 6 |
| R5 | Be honest about evidence | Every claim has a type. Sources carry dates and who has read them. See section 7 |
| R6 | Let the team review and revise | Direct editing, scoped AI changes with preview, accept, reject and Undo |
| R7 | Never lose work | Courses are files on disk with history, backups and recovery. See section 4 |
| R8 | Keep internal work internal | Notes, requests and review findings never enter an export |
| R9 | Use the owner's Claude subscription, and nothing paid beyond it | See section 5 |
| R10 | Never present filler as real | Simulated examples and real content are labelled differently everywhere |

## 3. How a course moves

```
Brief  →  Source research  →  Proposed outline  →  TEAM APPROVES
      →  Session materials  →  Checks  →  Team review and edits
      →  Approved version  →  Exported package  →  (separately) publication confirmed
```

| Step | Who | What happens |
|---|---|---|
| Brief | Team | One question on each screen. Follow-ups appear only when they change the course |
| Source research | Claude | Searches the web and opens pages. Loom records what was actually opened |
| Proposed outline | Claude | One outcome and one concrete task for each session, worked back from the course outcome |
| Approval gate | Team | The team reads, edits, asks for a different outline, or approves. **No lesson is written before approval** |
| Session materials | Claude | One request for each session. Each is saved as soon as it is finished |
| Checks | Loom and Claude | Loom's own consistency checks, then an independent review by Claude acting as a reviewer. The review judges seven areas: sources, feasibility, topic connections, assessment alignment, timing, clarity and continuity between sessions |
| Review and edits | Team | Direct edits and scoped AI changes |
| Approved version | Team | A locked snapshot. Later edits start a new draft. Open points (review findings marked "must fix", a review made on an earlier draft, sessions marked "Look", unchecked sources) must be ticked as read before approval, and are recorded with the version |
| Exported package | Team | A file holding learner and teacher materials, evidence, and what stood open at approval. It is named after the course and version. Exporting is not publishing |
| Publication | Website team | Recorded by hand in Loom after the website team confirms it |

## 4. Storage

Courses are files in `glitch-loom/data/`, written by Loom's local server.

| Record | Where | Notes |
|---|---|---|
| Working copy | `data/library/courses/<id>/course.json` | Brief, draft, undo history, approved snapshots, change log |
| One step back | `…/previous.json` | The copy that the latest save replaced. Always kept |
| Earlier copies | `…/history/` | A dated copy is kept at approval, export, weaving and restore, and every five minutes of editing. Up to 40. Saves made seconds apart are not all kept |
| Set-aside generations | `…/engine-history/` | The whole generation record, kept whenever a course is woven again or its outline is approved again |
| Generation record | `…/engine.json` | Sources, outline, each session as written, review, and a receipt for every request |
| Browser copies | `data/library/imports/` | Exact copies of work found in a browser's own storage when Loom moved to disk |
| Test storage | `data/test-stores/<name>/` | Used when the address has `?store=name`. Can never reach the real library. A misspelt or repeated storage name is refused, never treated as "no name" |

Rules:

1. Each course has its own brief, draft, history and approved versions. Starting a course never clears another.
2. Every save is checked in full before anything is written. It replaces the file atomically and keeps the copy it replaced. A save from an out-of-date window is refused. Data a browser could not read back (NaN, Infinity, anything that is not one JSON object) is refused.
3. Saved work that cannot be read is never overwritten. Loom shows a recovery screen and pauses saving.
4. A backup is one file holding the whole course. Restoring always creates a new course. A backup that cannot be read creates nothing.
5. Until a change reaches the disk, the browser also holds it. After a crash Loom offers it back.
6. Work saved by earlier versions in browser storage is copied into the library once. The browser's copy is left untouched.
7. Opening a course does not change it. Reading never creates folders.

## 5. The real generation path

Loom runs the Claude Code command-line tool in its documented non-interactive mode (`claude -p`), signed in with the owner's own Claude subscription.

| Safeguard | How |
|---|---|
| Subscription only | API keys and custom endpoints are removed from the tool's environment. A run is stopped if the tool reports an API key |
| Paid extra usage | A safeguard, not a guarantee. The request has started before the tool reports how it is billed. If it reports paid extra usage, Loom stops that request. Loom cannot see or change account settings |
| No other provider | None is configured |
| Isolation | The tool runs in an empty folder with the owner's settings, plugins, hooks and connectors switched off |
| Tools | Research may use web search and web fetch only. Every other step has no tools at all |
| One at a time | Requests run one after another. A request that is waiting its turn can still be stopped, and its time limit starts when it starts |
| Stops with the server | When the server is stopped, the running request is stopped too. If the server was killed outright, the next start stops what it left behind |
| Continuity | Each session after the first is written with the earlier sessions in front of Claude, as the team has them now: tasks, handouts, files, names and figures. Teacher notes and claims of other sessions are not sent |
| Failure | Any failure pauses the work with the reason. Finished parts stay saved. Resume does only what is unfinished |
| No silent substitution | A part that was not written is shown as not written. Simulated content is never used to fill a gap |
| Checks on answers | Every answer is checked by Loom. A failing answer gets one correction, then the work pauses |

Terms: Anthropic's documentation describes `claude -p` for scripts and the subscription sign-in for Claude Code. The Consumer Terms restrict automated access except where Anthropic explicitly permits it. Reading Claude Code's documented non-interactive mode as such a permitted route is Loom's reading, not legal advice. The decision to rely on it is the owner's.

## 6. What every session must contain

| Part | Rule |
|---|---|
| Outcome | One specific thing a learner can do by the end, with an observable verb |
| Serves | How it moves learners toward the course outcome |
| Prerequisites | Each one named, with the support for a learner who lacks it |
| Activities | In order. Minutes add up exactly to the session. Setup has its own time. The minutes are all the time there is: a sitting longer than 90 minutes holds a break inside them |
| Task | Numbered instructions a learner can follow. Any brief, text, data or template is written out in full |
| Worked example | Given when a skill is new to the learners. A different case from the task |
| Teacher guidance | What to watch for, what to say, when to step in |
| Misconceptions | What learners commonly get wrong, and the response |
| Feedback and revision | At least one feedback step followed by a revision step |
| Success criteria | At least two, each checkable by looking at the work |
| Later check | A task done alone, later, on a changed situation |
| Preparation | What the teacher does beforehand and how long it takes |
| Topic contributions | For joined topics: what each topic gives the task. "Weak" contributions are flagged |
| Claims | Every claim the materials rely on, with its type and sources |
| Continuity | Later sessions use exactly what earlier sessions produced. A conflict must be reported as the first assumption, not worked around silently |

Loom checks these parts are present. It cannot check that they are good, or that one session agrees with another. The independent review looks for that, and people decide.

## 7. Evidence

| Label | Meaning |
|---|---|
| Fact | A listed source directly supports it |
| Uncertain | Evidence is thin or disputed |
| Judgement | The writer's own reasoning, untested |
| Fiction | From a fictional world used as inspiration |

Each source records: title, address, publisher, kind, the claim it supports, what the page says, its limits, the retrieval date, whether Loom saw the page opened during research, whether the address opened when checked, and whether a person has read it.

Rules:

1. A source Claude lists but Loom never saw opened is kept, marked, and cannot back a fact.
1a. A claim cannot be called a fact when every source it cites is recorded as partial or background support. Loom sends such an answer back for correction, and lists such claims in existing drafts.
2. An address that opens is recorded as that and nothing more.
3. Only a person can mark a source as checked.
4. Topic ideas under "Trending now" and "Worth learning next" are illustrative until the team presses "Research this with Claude". That research opens pages on the web and keeps only ideas backed by a page that opened and shows a date; it names the ideas it could not back, records a failed search as failed, and never writes into the brief. "Use this idea" is the only way an answer changes.
5. Requirements from the brief (devices, language, accessibility) are shown as pending until a person confirms them.

## 8. Editing

| Way | Behaviour |
|---|---|
| Edit the text myself | Applies at once. Undo is available. Timing is recalculated |
| Ask Claude for a change | Scope is chosen first: this step, this session, or the whole journey. Claude is shown the rest of the course so the change can stay consistent with it, and is told not to rewrite it. A preview is shown. Nothing changes until it is accepted |
| Claude declines a request | The request is kept as an internal note |
| Undo | Restores the draft. Twelve steps are kept. An open preview of a simulated example is rebuilt. After undoing a change Claude wrote, that change is offered again as a preview |
| Moving between screens | Never discards a change Claude has written or is writing. It stays until accepted, rejected or given up |
| After approval | Any edit starts a new draft version. Approved snapshots never change |
| Dependents | Sessions that build on changed work are marked "Look". They are not rewritten |
| Brief changes | The journey is marked out of date. Loom lists what changed and what it affects. Approval is blocked until resolved |

## 9. Interface

| Principle | In the product |
|---|---|
| One decision on each screen | Question flow |
| Pill buttons | Answers, steps, actions |
| One world | A pixel-art valley drawn in code. Each question is a place. Answers build things there |
| Focused session view | A short list of steps. Details open on demand |
| One step at a time | Goal and duration visible. Tabs for learner, teacher, evidence and internal notes |
| Scenery stays visible | Session and step panels are narrow |
| Course list | A small button in the header. It stays out of the question flow |
| Honest progress | Step names and counts. No invented percentages |
| Motion | Short, interruptible, none on keyboard actions, none with reduced motion |
| Keyboard | Every control reachable. Radios and tabs follow standard arrow-key behaviour |

## 10. Readiness, in three separate categories

| Category | What would show it |
|---|---|
| UX usability | Team members completing real work without help |
| Data and workflow integrity | Automated checks and browser tests. See `ISSUES.md` |
| Curriculum quality | Teachers running the sessions and learners being assessed later. **Not yet done** |

A passing software test is not evidence that a course teaches well.

## 11. Not built yet

- Live trend research is built (see 4 above); whether a given run is good enough is the team's judgement, and it costs a request on the plan.
- Inspecting and exporting older approved versions from the interface.
- Subject profiles and a typed topic map shared across courses.
- Pilots with teachers and learners, and feeding results back into a course.
- Deleting or archiving a course.
- A place in the brief for group size and for notes beside each answer. Today these go in "Something else" under constraints.
- Writing one session again from the outline when it is already written. Today that is done with "Ask Claude for a change".
