#!/usr/bin/env python3
"""Inspect a downloaded Loom package against the course it came from.

Usage: python3 tests/tools/inspect_export.py <downloaded package.json> <course folder> [version]

It reads the real downloaded file. It checks structure, timing and leaks. It cannot judge whether the course teaches well.
"""
import json
import re
import sys
from pathlib import Path

pkg_path, course_dir = Path(sys.argv[1]), Path(sys.argv[2])
pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
state = json.loads((course_dir / "course.json").read_text(encoding="utf-8"))
engine = json.loads((course_dir / "engine.json").read_text(encoding="utf-8")) if (course_dir / "engine.json").exists() else {}
version = int(sys.argv[3]) if len(sys.argv) > 3 else pkg.get("version")
text = json.dumps(pkg, ensure_ascii=False)
problems, notes = [], []


def check(ok, what):
    (notes if ok else problems).append(("PASS  " if ok else "FAIL  ") + what)


snap = next((s for s in state["life"]["snapshots"] if s["ver"] == version), None)
check(snap is not None, f"the course holds an approved snapshot for version {version}")
check(pkg.get("version") == version, f"the package says it is version {version}")
if snap:
    j = snap["journey"]
    check(pkg.get("approvedAt") == snap["at"], "the approval time in the package is the snapshot's")
    check([s["title"] for s in pkg["learnerMaterials"]] == [s["title"] for s in j["sessions"]], "session titles match the approved snapshot, in order")
    for i, s in enumerate(j["sessions"]):
        ls, ts = pkg["learnerMaterials"][i], pkg["teacherMaterials"][i]
        steps = ls["steps"]
        check(sum(x["minutes"] for x in steps) == ls["minutes"] == s["minutes"], f"session {i + 1}: step minutes add up to {ls['minutes']}, as approved")
        check([x.get("instructions") for x in steps] == [x.get("instructions") for x in s["activities"]], f"session {i + 1}: learner instructions are word for word the approved ones")
        check([x.get("handout", "") for x in steps] == [x.get("handout", "") for x in s["activities"]], f"session {i + 1}: handouts are word for word the approved ones")
        check(len(ts["stepNotes"]) == len(steps), f"session {i + 1}: every step has teacher notes")
        if j.get("origin") == "claude":
            check(bool(ls.get("successCriteria")) and bool(ls.get("laterCheck")), f"session {i + 1}: success criteria and a later check are present")
            check(all(x.get("instructions") or x["step"] in ("Set up", "Break") for x in steps), f"session {i + 1}: every step has instructions, except setup and breaks")
    total = sum(s["minutes"] for s in pkg["learnerMaterials"])
    check(total == pkg["course"]["planned"]["minutes"], f"planned minutes ({pkg['course']['planned']['minutes']}) equal the sum of sessions ({total})")
    asked = pkg["course"]["requestedInBrief"]["minutes"]
    check(pkg["course"]["plannedDiffersFromBrief"] == (total != asked or pkg["course"]["planned"]["sessions"] != pkg["course"]["requestedInBrief"]["sessions"]), f"'differs from brief' is {pkg['course']['plannedDiffersFromBrief']}: brief asked {asked} min, plan has {total} min")
    for t in pkg["course"]["topics"]:
        where = [i + 1 for i, s in enumerate(pkg["teacherMaterials"]) if any(str(c.get("topic", "")).lower() == t.lower() and str(c.get("gives", "")).strip() for c in s.get("whatEachTopicContributes") or [])]
        check(bool(where), f"topic “{t}” has a stated contribution in sessions {where}")

    # leaks: anything that is internal must not be in the file
    internal = []
    for s in j["sessions"]:
        internal += s.get("internal") or []
        if s.get("review"):
            internal.append(s["review"].get("reason", ""))
        for x in s["activities"]:
            internal += x.get("internal") or []
    internal += j.get("internal") or []
    reviews = []
    for src in (j.get("review") or {}, state.get("journey", {}).get("review") or {}, {"output": (engine.get("stages", {}).get("review") or {}).get("output")}):
        out = src.get("output") or {}
        for f in out.get("findings") or []:
            reviews += [f.get("finding", ""), f.get("suggestion", "")]
        reviews += [a.get("summary", "") for a in out.get("areas") or []]
        reviews.append((out.get("teacher_could_run_it") or {}).get("why", ""))
    requests = [e.get("instruction", "") for e in (engine.get("edits") or {}).values()]
    log = [str(l.get("label", "")) for l in state.get("log") or [] if l.get("what") not in ("Outline approved",)]
    for name, items in (("internal note", internal), ("review text", reviews), ("change request", requests)):
        hits = [t for t in items if isinstance(t, str) and len(t.strip()) > 25 and t.strip() in text]
        check(not hits, f"no {name} is in the file ({len([t for t in items if isinstance(t, str) and t.strip()])} checked)" + (": " + hits[0][:80] if hits else ""))
    for marker in ("Request for the writer", "Not acted on", "<task ", "WRITING_RULES", "structured output", "You are working inside Glitch Loom", "TEST DOUBLE", "Simulated example"):
        check(marker.lower() not in text.lower(), f"the file does not contain “{marker}”")
    check("standingAtApproval" in pkg, "the file says what stood open at approval")
    ev = pkg.get("evidence") or {}
    srcs = ev.get("sources") or []
    check(bool(srcs) and all(s.get("url") and (s.get("askedForOn") or s.get("retrievedOn")) for s in srcs), f"{len(srcs)} sources, each with an address and the date the AI asked for it")
    check(all((s.get("pageReachedTheAI") == "yes") == bool(s.get("retrievedOn")) for s in srcs if "pageReachedTheAI" in s), "a retrieval date is given only for a page that reached the AI")
    check(all((s.get("readByAPersonOn") or s.get("checkedByAPersonOn")) is None or re.match(r"^\d{4}-", str(s.get("readByAPersonOn") or s.get("checkedByAPersonOn"))) for s in srcs), "no source is shown as checked by a person unless a date was recorded")
    claims = ev.get("claims") or []
    ids = {s["id"] for s in srcs}
    check(all(set(c.get("sources") or []) <= ids for c in claims), f"{len(claims)} claims cite only listed sources")
    facts_without = [c for c in claims if c["type"] == "fact" and not c.get("sources")]
    check(not facts_without, "no claim is called a fact without a source")
    by = {}
    for c in claims:
        by[c["type"]] = by.get(c["type"], 0) + 1
    notes.append(f"INFO  claims by type: {by}")
    notes.append(f"INFO  standing at approval: {json.dumps(pkg.get('standingAtApproval'), ensure_ascii=False)[:700]}")

print(f"File: {pkg_path}  ({pkg_path.stat().st_size} bytes)")
print(f"Course: {course_dir.name}  package version {pkg.get('version')}  exported {pkg.get('exportedAt')}")
for line in notes + problems:
    print(line)
print(f"\n{len(problems)} problem(s), {len([n for n in notes if n.startswith('PASS')])} checks passed.")
sys.exit(1 if problems else 0)
