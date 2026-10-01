#!/usr/bin/env python3
"""Rehearse the budgeting pack by doing what its own pages say, in order, on a sheet built from its own pages.

Usage: python3 tests/tools/rehearse_budget_sheet.py <course folder> [--snapshot N]

What it does
  1. Builds each sheet from the layout the pack prints (cell, label, value or formula).
  2. Replays each teacher demo step by step: every "click, type", "change X to Y", "delete" and "Ctrl+Z",
     and compares every figure the script tells the teacher to read out with what the sheet then shows.
  3. Walks the learner task for every card, down every branch the instructions allow.

What it does not do
  It uses no spreadsheet program. Menus, file formats, typing slips and what a beginner finds hard are not covered.
  It reads only sentences it can parse, and says how many it replayed. It is a check on the pack's own consistency,
  not on whether the pack teaches well.
"""
import json
import re
import sys
from pathlib import Path

folder = Path(sys.argv[1])
state = json.loads((folder / "course.json").read_text())
journey = state["journey"]
if "--snapshot" in sys.argv:
    n = int(sys.argv[sys.argv.index("--snapshot") + 1])
    journey = next(s for s in state["life"]["snapshots"] if s["ver"] == n)["journey"]
fails, passes = [], 0


def check(cond, what):
    global passes
    if cond:
        passes += 1
    else:
        fails.append(what)
    print(("PASS  " if cond else "FAIL  ") + what)


class Sheet:
    def __init__(self):
        self.cells, self.undo = {}, []

    def put(self, ref, value, note=True):
        if note:
            self.undo.append((ref, self.cells.get(ref)))
        if value is None:
            self.cells.pop(ref, None)
        else:
            self.cells[ref] = value

    def back(self, times):
        for _ in range(times):
            if not self.undo:
                return False
            ref, old = self.undo.pop()
            self.put(ref, old, note=False)
        return True

    def value(self, ref, depth=0):
        v = self.cells.get(ref)
        if v is None or depth > 20:
            return 0
        if isinstance(v, (int, float)):
            return v
        if not str(v).startswith("="):
            return 0  # text counts as nothing in a sum
        return self.formula(str(v)[1:], depth + 1)

    def formula(self, f, depth):
        f = f.replace(" ", "")

        def total(m):
            out = 0
            for part in re.split(r"[,;]", m.group(1)):
                r = re.fullmatch(r"([A-Z])(\d+):([A-Z])(\d+)", part)
                if r:
                    out += sum(self.value(f"{r.group(1)}{i}", depth) for i in range(int(r.group(2)), int(r.group(4)) + 1))
                else:
                    out += self.value(part, depth)
            return str(out)
        f = re.sub(r"SUM\(([^()]*)\)", total, f)
        f = re.sub(r"[A-Z]\d+", lambda m: "(" + str(self.value(m.group(0), depth)) + ")", f)
        if not re.fullmatch(r"[-+0-9.()]+", f):
            raise ValueError("cannot read formula: " + f)
        return eval(f, {"__builtins__": {}})  # digits, brackets, plus and minus only, checked above


LAYOUT = re.compile(r"^A(\d+):?\s+(.*?)\s+B\1:?\s+(=\S+|-?\d+|\(.*?\))(?:\s.*?)??(?:\s+(?:->\s*)?shows\s+(-?\d+))?\s*(?:C\1.*)?$")


def build(text):
    """A sheet from the lines of a printed layout. Returns the sheet and the figures the layout says it shows."""
    s, shown = Sheet(), {}
    for line in text.splitlines():
        m = LAYOUT.match(line.strip())
        if not m:
            continue
        row, label, val, shows = m.groups()
        if re.match(r"\(?(leave )?empty", val, re.I):
            continue
        s.put(f"A{row}", label.strip(), note=False)
        s.put(f"B{row}", val if val.startswith("=") else int(val) if re.fullmatch(r"-?\d+", val) else val, note=False)
        if shows is not None:
            shown[f"B{row}"] = int(shows)
    return s, shown


WORDS = {"once": 1, "twice": 2, "two times": 2, "three times": 3, "four times": 4, "five times": 5}
SAID = re.compile(r"\b(B\d+)(?: (?:still|now|again))?(?: (?:shows?|reads?|is back to|goe?s? to|go to|drops to|as it drops to))? (-?\d+)\b(?! to\b)")


def replay(name, script):
    """Do what a demo script says, sentence by sentence."""
    sheet, shown = build(script)
    check(len(shown) >= 8, f"{name}: a sheet could be built from the printed layout ({len(sheet.cells) // 2} rows, {len(shown)} stated figures)")
    for ref, want in shown.items():
        if sheet.value(ref) != want:
            check(False, f"{name}: the layout says {ref} shows {want}; the sheet shows {sheet.value(ref)}")
    done = said = 0
    last_cost = None
    body = script[script.find("STEP 1"):] if "STEP 1" in script else script
    for step in re.split(r"(?=STEP \d+\.)", body):
        label = re.match(r"STEP \d+", step).group(0) if step.startswith("STEP") else "start"
        for sentence in re.split(r"(?<=[.!?])\s+|\n", step):
            t = sentence.strip()
            if not t or t.startswith(("Say", '"', "Reason to say", "Write on the board", "RESPONSE", "What I changed", "New left over", "If it came")) or " would " in t or t.count('"') % 2:
                continue
            for m in re.finditer(r"[Cc]lick ([AC]\d+)(?:,| and) type:? ?([^.\n]*)", t):
                sheet.put(m.group(1), m.group(2).strip() or "text"); done += 1
            for m in re.finditer(r"[Cc]lick (B\d+)(?:,| and) type (-?\d+)", t):
                sheet.put(m.group(1), int(m.group(2))); last_cost = int(m.group(2)); done += 1
            for m in re.finditer(r"[Cc]lick (B\d+) and change (-?\d+) to (-?\d+)", t):
                ref, old, new = m.group(1), int(m.group(2)), int(m.group(3))
                check(sheet.value(ref) == old, f"{name}, {label}: {ref} holds {old} before it is changed to {new} (the sheet holds {sheet.value(ref)})")
                sheet.put(ref, new); done += 1
            m = re.search(r"Delete (A\d+) and (B\d+)", t)
            if m:
                sheet.put(m.group(1), None); sheet.put(m.group(2), None); done += 2
            m = re.search(r"Put the cost back in (A\d+) and (B\d+)", t)
            if m and last_cost is not None:
                sheet.put(m.group(1), "cost"); sheet.put(m.group(2), last_cost); done += 2
            m = re.search(r"Ctrl\+Z(?: \(Cmd\+Z\))? (once|twice|\w+ times)", t)
            if m:
                k = WORDS.get(m.group(1), 1)
                check(sheet.back(k), f"{name}, {label}: there were {k} steps to undo"); done += 1
            m = re.search(r"so row (\d+) is empty", t)
            if m:
                check(f"B{m.group(1)}" not in sheet.cells, f"{name}, {label}: row {m.group(1)} is empty when the script says it is")
            lists = re.search(r"((?:B\d+(?:, | and ))+B\d+) (?:read|show|reads|shows) ((?:-?\d+(?:, | and ))+-?\d+)", t)
            if lists:
                refs, nums = re.findall(r"B\d+", lists.group(1)), [int(x) for x in re.findall(r"-?\d+", lists.group(2))]
                if len(refs) == len(nums):
                    for ref, want in zip(refs, nums):
                        said += 1
                        check(sheet.value(ref) == want, f"{name}, {label}: the script says {ref} is {want}; after the steps so far the sheet shows {sheet.value(ref)}")
                    t = t.replace(lists.group(0), " ")
            claims = re.sub(r"[Cc]lick B\d+(?:,| and) (?:type|change) -?\d+(?: to -?\d+)?|from -?\d+ to -?\d+|=[A-Z0-9:(),;+\-]+", " ", t)
            for m in SAID.finditer(claims):
                said += 1
                ref, want = m.group(1), int(m.group(2))
                check(sheet.value(ref) == want, f"{name}, {label}: the script says {ref} is {want}; after the steps so far the sheet shows {sheet.value(ref)}")
        for m in re.finditer(r"row (\d+),? which is empty|[Rr]ow (\d+) is (?:still )?empty|empty row at (\d+)", step):
            row = next(g for g in m.groups() if g)
            if " would " in step[max(0, m.start() - 200):m.start()] and "which is empty" in m.group(0):
                check(f"B{row}" not in sheet.cells, f"{name}, {label}: the script calls row {row} empty; at that point it holds {sheet.cells.get('B' + row)}")
    print(f"INFO  {name}: replayed {done} actions and compared {said} figures that the script reads out")
    check(done >= 5 and said >= 5, f"{name}: enough of the script could be read to call this a rehearsal")
    return sheet


def texts(session, keys):
    return [(a["title"], k, a.get(k) or "") for a in session["activities"] for k in keys]


# ---- 1. every teacher demo that prints a whole layout and then steps
demos = 0
for si, session in enumerate(journey["sessions"]):
    for title, key, text in texts(session, ("example",)):
        if sum(1 for line in text.splitlines() if LAYOUT.match(line.strip())) >= 8 and "STEP 1" in text:
            demos += 1
            replay(f"session {si + 1} demo “{title[:40]}”", text)
check(demos >= 1, f"{demos} teacher demo(s) could be replayed from a printed layout")

# ---- 2. the learner's own sheet, built from the layout the pack gives
alex = None
for session in journey["sessions"]:
    for title, key, text in texts(session, ("handout", "example")):
        s, shown = build(text)
        if shown.get("B9") == 3040 and "B33" in s.cells and alex is None:
            alex = text
check(alex is not None, "the pack prints the learner's own sheet (Alex's month, money in 3040)")
everything = json.dumps(journey["sessions"], ensure_ascii=False)
SUMMARY = {"B38": "=B9", "B39": "=B17", "B40": "=B25", "B41": "=B33", "B42": "=SUM(B39:B41)", "B43": "=B42-SUM(B13:B16,B21:B24,B29:B32)", "B44": "=B42-B35", "B45": "=B38-B42"}
for ref, f in SUMMARY.items():
    check(f in everything, f"the pack tells learners to type {f} in {ref}")
ROWS = {"fixed": range(13, 17), "variable": range(21, 25), "discretionary": range(29, 33)}
TOTAL = {"fixed": "B17", "variable": "B25", "discretionary": "B33"}


def learner_sheet(gym_in="as printed"):
    s, _ = build(alex)
    for ref, f in SUMMARY.items():
        s.put(ref, f, note=False)
    gym = next((r for r in range(13, 33) if "gym" in str(s.cells.get(f"A{r}", "")).lower()), None)
    if gym and gym_in in ROWS and gym not in ROWS[gym_in]:
        free = next(r for r in ROWS[gym_in] if f"B{r}" not in s.cells)
        for col in "AB":
            s.put(f"{col}{free}", s.cells[f"{col}{gym}"], note=False)
            s.put(f"{col}{gym}", None, note=False)
    return s


if alex:
    cards = dict((m.group(1), int(m.group(2))) for m in re.finditer(r"CARD ([AB]\d)\\n(?:(?!CARD )[^\"])*?(?:charges|bill is|costs?|comes? to|fee of|by|: )\s*(\d{2,4})\b", everything))
    check(len(cards) >= 8, f"the shock cards could be read: {cards}")
    base = learner_sheet()
    start = base.value("B45")
    check((base.value("B9"), base.value("B35"), start, base.value("B43"), base.value("B44")) == (3040, 2632, 408, 0, 0), "the learner's sheet starts at money in 3040, money out 2632, left over 408, both checks 0")
    branches, bad = 0, []
    for card, amount in cards.items():
        for gym_in in ("fixed", "discretionary"):
            for group in ROWS:
                s, before = learner_sheet(gym_in), learner_sheet(gym_in)
                free = next((r for r in ROWS[group] if f"B{r}" not in s.cells), None)
                if free is not None:  # the instruction: the first empty row inside that block
                    s.put(f"A{free}", "cost"); s.put(f"B{free}", amount)
                    how = f"typed into empty row {free}"
                else:  # the instruction when the block is full: add to a row already in that block, and say so in column C
                    r = ROWS[group][0]
                    s.put(f"B{r}", s.value(f"B{r}") + amount); s.put(f"C{r}", f"{amount} of this is today's cost")
                    how = f"added to row {r} because the block is full"
                ok = (s.value("B45") == start - amount and s.value("B43") == 0 and s.value("B44") == 0 and s.value(TOTAL[group]) == before.value(TOTAL[group]) + amount
                      and all(s.value(TOTAL[g]) == before.value(TOTAL[g]) for g in ROWS if g != group))
                branches += 1
                if not ok:
                    bad.append(f"card {card} ({amount}), gym in {gym_in}, cost in {group}, {how}: left over {s.value('B45')}, checks {s.value('B43')} and {s.value('B44')}")
    check(not bad, f"{branches} learner branches walked (each card, the gym sorted either way, each group, empty row or full block): the cost lands in its own group's subtotal and in no other, B45 falls by exactly the cost, both checks stay 0, and no address moves" + ("".join("\n        " + b for b in bad[:5])))
    # The combined case: the block is full, so the cost goes onto a row that already has an expense, and is then split.
    # Column B is everything that row pays this month, so the expense that was already there must survive the split.
    gym = next((r for r in range(13, 33) if "gym" in str(learner_sheet().cells.get(f"A{r}", "")).lower()), None)
    wedding = cards.get("A5")
    if gym and wedding:
        half = wedding // 2
        s, was = learner_sheet(), learner_sheet().value(f"B{gym}")
        s.put(f"B{gym}", was + wedding)  # the whole cost added onto the occupied row
        check(s.value("B45") == start - wedding, f"the whole cost added onto the gym row ({was}) takes the full {wedding} off the left over figure")
        s.put(f"B{gym}", was + half)  # split: this month's part on top of what the row already paid
        s.put(f"C{gym}", f"gym {was} + wedding {half} of {wedding}, {half} due next month")
        check(s.value(f"B{gym}") == was + half == 375, f"a split on an occupied row leaves column B at {was} + {half} = {was + half}, not {half}")
        check(s.value("B45") == start - half and s.value("B43") == 0 and s.value("B44") == 0,
              f"after the split the left over figure is {start} - {half} = {start - half}, and both checks still read 0")
        wrong = learner_sheet(); wrong.put(f"B{gym}", half)  # the mistake the pack must not invite
        check(wrong.value("B45") == start - half + was,
              f"typing only {half} over the gym's {was} would silently drop that expense and leave the sheet claiming {start - half + was} instead of {start - half}")
        told = [m for m in re.findall(r"[^.\"]{0,140}375[^.\"]{0,80}", everything) if "350" in m]
        check(told, "the pack tells learners in so many words that this case reads 375, not 350" + ("" if told else ""))
        keeps = re.findall(r"[^.\"]{0,120}(?:everything that row pays|plus this month's part|plus the cost|added together)[^.\"]{0,80}", everything)
        check(len(keeps) >= 4, f"the rule that column B holds the whole of what the row pays is stated where it is needed ({len(keeps)} places)")

    s = learner_sheet(); s.put("A26", "cost"); s.put("B26", 520)
    check(s.value("B45") == start and s.value("B43") == 0 and s.value("B44") == 0, "a cost typed in row 26, outside every block, changes nothing and both checks still read 0: the checks cannot see it")
    proof = re.findall(r"[^.\"]*B43 and B44[^.\"]*(?:so no row fell outside|proves? (?:that )?no|nothing (?:is|was) (?:missed|left out))[^.\"]*", everything)
    check(not proof, "no criterion claims that the two checks prove nothing was left out" + (": " + proof[0][:100] if proof else ""))
    s = learner_sheet(); s.put("B25", "=SUM(B21:B23)"); s.put("B24", 300)
    check(s.value("B43") != 0, "a group total whose range stops short of row 24 is caught by check 1")
    s = learner_sheet(); s.put("B35", "=SUM(B13:B33)")
    check(s.value("B44") != 0, "a total money out that counts the subtotals twice is caught by check 2")

for gone in ["B46", "Insert Rows Above", ".csv", "use row 24 and write the group", "Google Sheets, use that"]:
    left = [m for m in re.findall(r"[^.\"]{0,60}" + re.escape(gone) + r"[^.\"]{0,40}", everything) if not re.search(r"\b(not|no|never|cannot)\b", m, re.I)]
    check(not left, f"no instruction still depends on “{gone}”" + (f": {left[0].strip()[:90]}" if left else ""))

print(f"\n{passes} checks passed, {len(fails)} failed.")
for f in fails:
    print("  FAILED: " + f)
sys.exit(1 if fails else 0)
