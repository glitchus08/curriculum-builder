"""The parts of the expanded curriculum pipeline that need no model: they are plain rules, so they can be tested and trusted.

  * the topic and prerequisite map: is it well formed, does it hold every requested topic, is anything orphaned or circular
  * what a course of this size must contain (projects) and how live and independent time add up
  * the checks an outline must pass against the map, including order, coverage, projects and time
  * running the code a course supplies, in a sandbox, so that "the starter and solution work" is a fact and not a hope

Nothing here judges whether a topic is correct or whether a source supports a claim. That is for the reviewers and, in the end, for people.
"""
from __future__ import annotations

import ast
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_NODES = 40
MAX_RESEARCH_NODES = 18  # nodes researched in one run; the rest are named as not researched
BATCH_SIZE = 4
OUTCOME = "OUTCOME"
ROLES = ("required", "optional", "already_known", "excluded")


def norm_url(u: str) -> str:
    import urllib.parse
    try:
        p = urllib.parse.urlsplit(u.strip())
        return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query else "")
    except ValueError:
        return u.strip()


def norm(name) -> str:
    """One spelling of a topic name, so “Data cleaning” and “data-cleaning ” are the same node."""
    import string
    keep = {"+", "#"}
    t = "".join(" " if (c in string.punctuation and c not in keep) else c for c in str(name or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


# ---------------------------------------------------------------- the map

def derive_map(m: dict) -> dict:
    """Fill in what follows from the map itself: who needs whom, a teaching order, levels, and the gaps still open.

    The model's own `needed_by` is kept, and anything a `requires` line implies is added to it. Returns a new dict.
    """
    nodes = [dict(n) for n in m.get("nodes") or [] if isinstance(n, dict)]
    by = {n.get("id"): n for n in nodes}
    for n in nodes:
        n["needed_by"] = list(dict.fromkeys(x for x in n.get("needed_by") or [] if isinstance(x, str)))
        n["requires"] = [r for r in dict.fromkeys(n.get("requires") or []) if isinstance(r, str)]
    for n in nodes:
        for r in n["requires"]:
            if r in by and n["id"] not in by[r]["needed_by"]:
                by[r]["needed_by"].append(n["id"])
    # Kahn's algorithm, keeping the model's own order when there is a choice.
    indeg = {n["id"]: len([r for r in n["requires"] if r in by]) for n in nodes}
    order, ready = [], [n["id"] for n in nodes if indeg[n["id"]] == 0]
    while ready:
        i = ready.pop(0)
        order.append(i)
        for n in nodes:
            if i in n["requires"] and n["id"] in indeg:
                indeg[n["id"]] -= 1
                if indeg[n["id"]] == 0:
                    ready.append(n["id"])
    level = {}
    for i in order:
        n = by[i]
        level[i] = 1 + max([level.get(r, 0) for r in n["requires"] if r in level] or [0])
    live = [n for n in nodes if n.get("role") in ("required", "optional")]
    # A gap is a needed topic that a learner at the stated level cannot begin AND that has nothing below it in the map to lead up to it.
    # A topic whose own prerequisites are in the map is not a gap: those prerequisites are what get it started.
    gaps = [f"“{n.get('name')}” is needed, but nothing in the map leads up to it and a learner at the stated starting level cannot begin it: {_txt(n.get('below_entry')) or 'nothing was said about what lies below it'}."
            for n in live if n.get("entry_reached") is False and not [r for r in n["requires"] if r in by]]
    out = dict(m, nodes=nodes)
    out["derived"] = {"order": order + [n["id"] for n in nodes if n["id"] not in order], "levels": level,
                      "requiredMinutes": sum(int(n.get("est_minutes") or 0) for n in nodes if n.get("role") == "required"),
                      "optionalMinutes": sum(int(n.get("est_minutes") or 0) for n in nodes if n.get("role") == "optional"),
                      "openGaps": gaps, "unresolved": [g for g in (m.get("unresolved") or []) if _txt(g)]}
    # A topic that says it needs something the map does not hold. The ordering simply skipped these, so a
    # prerequisite the map itself named went nowhere and nothing said so — the quiet dropping the map exists
    # to prevent. Named here, so it is visible beside the gaps rather than inferred from an empty space.
    dangling = [{"node": n["id"], "name": n.get("name"), "needs": r}
                for n in nodes for r in (n.get("requires") or []) if r not in by]
    if dangling:
        out["derived"]["danglingRequirements"] = dangling
        out["derived"]["unresolved"] = out["derived"]["unresolved"] + [
            f"{d['name'] or d['node']} says it needs {d['needs']}, which is not a topic in this map"
            for d in dangling]
    return out


def find_cycle(nodes: list) -> list:
    by = {n["id"]: n for n in nodes}
    state, stack = {}, []

    def visit(i):
        state[i] = 1
        stack.append(i)
        for r in by[i].get("requires") or []:
            if r not in by:
                continue
            if state.get(r) == 1:
                return stack[stack.index(r):] + [r]
            if state.get(r) is None:
                c = visit(r)
                if c:
                    return c
        state[i] = 2
        stack.pop()
        return None

    for i in by:
        if state.get(i) is None:
            c = visit(i)
            if c:
                return c
    return []


def check_map(m: dict, brief: dict) -> list:
    """Problems that send the map back to its author. Semantic quality is left to the foundations reviewer."""
    p, topics = [], brief.get("topics") or []
    nodes = [n for n in m.get("nodes") or [] if isinstance(n, dict)]
    if not nodes:
        return ["The map has no topics."]
    if len(nodes) > MAX_NODES:
        p.append(f"The map has {len(nodes)} topics. The most Loom plans is {MAX_NODES}. Merge or drop the least necessary and say so in 'unresolved'.")
    ids = [n.get("id") for n in nodes]
    if any(not _txt(i) for i in ids) or len(set(ids)) != len(ids):
        p.append("Every topic needs its own id, and no two may share one.")
        return p
    names = {}
    for n in nodes:
        k = norm(n.get("name"))
        if not k:
            p.append(f"Topic {n['id']} has no name.")
        elif k in names:
            p.append(f"“{n.get('name')}” appears twice ({names[k]} and {n['id']}). One shared foundation is one topic, needed by everything that needs it.")
        names[k] = n["id"]
    byid = {n["id"]: n for n in nodes}
    for t in topics:
        hit = [n for n in nodes if norm(n.get("name")) == norm(t)]
        if not hit:
            p.append(f"The requested topic “{t}” is not in the map. Every requested topic must be a topic in it, with its own name.")
        elif hit[0].get("kind") != "requested" or hit[0].get("role") != "required":
            p.append(f"“{t}” was requested, so its kind is 'requested' and its role is 'required'.")
    for n in nodes:
        nm = f"“{n.get('name')}”"
        if n.get("kind") == "requested" and norm(n.get("name")) not in {norm(t) for t in topics}:
            p.append(f"{nm} is marked 'requested', but the team did not ask for it. Requested topics are only the ones in the brief; anything else is a foundation or a subtopic.")
        if n.get("role") not in ROLES:
            p.append(f"{nm} has an unknown role.")
        for ref in (n.get("requires") or []):
            if ref not in byid:
                p.append(f"{nm} requires {ref}, which is not in the map.")
            elif ref == n["id"]:
                p.append(f"{nm} requires itself.")
        for ref in (n.get("needed_by") or []):
            if ref != OUTCOME and ref not in byid:
                p.append(f"{nm} says it is needed by {ref}, which is not in the map.")
        if n.get("kind") in ("foundation", "subtopic") and not _txt(n.get("why_needed")):
            p.append(f"{nm} was added but does not say why it is needed.")
        if n.get("role") in ("required", "optional"):
            if not isinstance(n.get("est_minutes"), int) or not (5 <= n["est_minutes"] <= 600):
                p.append(f"{nm} needs an honest estimate of teaching and practice time, a whole number of minutes from 5 to 600.")
        if n.get("role") == "excluded" and not _txt(n.get("why_needed")):
            p.append(f"{nm} is excluded, so 'why_needed' must say why it is left out.")
    cyc = find_cycle([dict(n, requires=[r for r in n.get("requires") or []]) for n in nodes])
    if cyc:
        p.append("The map has a circle: " + " → ".join(f"“{byid[i].get('name')}”" for i in cyc) + ". A topic cannot need itself. Break the circle.")
    if p:
        return p
    d = derive_map(m)
    # Everything added must lead back to a requested topic or to the outcome. An addition nothing needs is unrelated material.
    justified = {n["id"] for n in d["nodes"] if OUTCOME in n["needed_by"] or n.get("kind") == "requested"}
    changed = True
    while changed:
        changed = False
        for n in d["nodes"]:
            if n["id"] not in justified and any(x in justified for x in n["needed_by"]):
                justified.add(n["id"])
                changed = True
    for n in d["nodes"]:
        if n["id"] not in justified and n.get("role") != "excluded":
            p.append(f"“{n.get('name')}” is in the map but nothing that is requested needs it, directly or through another topic. Remove it, or say what needs it.")
    for n in d["nodes"]:
        if n.get("role") == "required":
            for r in n["requires"]:
                if byid[r].get("role") == "excluded":
                    p.append(f"“{n.get('name')}” is required but needs “{byid[r].get('name')}”, which the map excludes. Either keep it or explain what replaces it.")
    return p


def add_nodes(m: dict, additions: list, source: str) -> tuple[dict, list]:
    """Add topics a reviewer says are missing. Returns the new map and the names added. A name already in the map is not added twice."""
    m = dict(m, nodes=[dict(n) for n in m.get("nodes") or []])
    have = {norm(n.get("name")): n for n in m["nodes"]}
    taken = {n["id"] for n in m["nodes"]}
    added, num = [], 1
    for a in additions or []:
        name = _txt(a.get("name"))
        if not name or norm(name) in have:
            continue
        while f"N{num}" in taken:
            num += 1
        nid = f"N{num}"
        taken.add(nid)
        by_name = {norm(n.get("name")): n["id"] for n in m["nodes"]}
        need = [by_name.get(norm(x), x) for x in a.get("needed_by") or []]
        need = [x for x in need if x == OUTCOME or x in taken or x in {n["id"] for n in m["nodes"]}] or [OUTCOME]
        req = [by_name.get(norm(x), x) for x in a.get("requires") or []]
        node = {"id": nid, "name": name, "kind": a.get("kind") if a.get("kind") in ("foundation", "subtopic") else "foundation", "role": "required", "why_needed": _txt(a.get("why_needed")) or "Added by the foundations reviewer.",
                "needed_by": need, "requires": [r for r in req if r in taken], "depth": "working", "entry_reached": True, "below_entry": "", "est_minutes": a.get("est_minutes") if isinstance(a.get("est_minutes"), int) and 5 <= a["est_minutes"] <= 600 else 30,
                "needs_evidence": True, "research_questions": [], "addedBy": source}
        m["nodes"].append(node)
        have[norm(name)] = node
        added.append(name)
        # Whatever the new topic is needed by now requires it, so the teaching order follows.
        for x in need:
            for n in m["nodes"]:
                if n["id"] == x and nid not in n.get("requires", []) and x != nid:
                    n["requires"] = list(n.get("requires") or []) + [nid]
    return m, added


# ---------------------------------------------------------------- size, time and projects

def project_policy(plan: dict) -> dict:
    """What a course of this size is expected to hold. A rule of thumb, stated to the team, that they may argue with."""
    total = int(plan.get("total") or 0) + int((plan.get("independent") or {}).get("totalMinutes") or 0)
    if total < 90:
        return {"minor": 0, "major": 0, "note": "Too short for a project. A short format practises one skill; the fuller pathway is offered separately, not squeezed in."}
    if total < 240:
        return {"minor": 1, "major": 0, "note": "One applied task that produces something a learner can show."}
    if total < 600:
        return {"minor": 1, "major": 1, "note": "One practice project, and one project that pulls the skills together."}
    return {"minor": 2, "major": 1, "note": "At least two practice projects, and one capstone that integrates the outcomes."}


def accounting(plan: dict) -> dict:
    live = int(plan.get("total") or sum(plan.get("minutes") or []))
    ind = plan.get("independent") or {}
    own = int(ind.get("totalMinutes") or 0)
    return {"liveMinutes": live, "independentMinutes": own, "combinedMinutes": live + own,
            "statement": f"{live // 60 if live % 60 == 0 else live / 60:g} h live" + (f" + {own // 60 if own % 60 == 0 else own / 60:g} h independent = {(live + own) / 60:g} h. Each hour is counted once." if own else " in total.")}


def week_of(plan: dict, session_number: int) -> int:
    k = int(plan.get("meetingsPerWeek") or 1) if plan.get("weekly") else 1
    return (session_number - 1) // max(1, k) + 1


def check_outline_v2(out: dict, m: dict, brief: dict, plan: dict) -> list:
    """Checks that need the map. They run in addition to the ordinary outline checks."""
    p = []
    nodes = {n["id"]: n for n in m.get("nodes") or []}
    n_s = plan["sessions"]
    sessions = out.get("sessions") or []
    taught_in: dict = {}
    for i, s in enumerate(sessions, 1):
        for k in ("teaches", "practises"):
            for nid in s.get(k) or []:
                if nid not in nodes:
                    p.append(f"Session {i} lists {nid} under {k}, which is not in the map.")
        for nid in s.get("teaches") or []:
            taught_in.setdefault(nid, i)
    deferred = {d.get("node"): d for d in out.get("deferred") or [] if isinstance(d, dict)}
    trimmed = {d.get("node"): d for d in out.get("trimmed") or [] if isinstance(d, dict)}
    tc = out.get("time_conflict") or {}
    for nid in taught_in:
        if nodes.get(nid, {}).get("role") in ("excluded", "already_known"):
            p.append(f"Session {taught_in[nid]} teaches “{nodes[nid].get('name')}”, which the map marks {nodes[nid].get('role').replace('_', ' ')}. Either teach it and make it required, or leave it out.")
    for nid in deferred:
        if nid in taught_in:
            p.append(f"“{nodes.get(nid, {}).get('name', nid)}” is listed as deferred and is also taught in session {taught_in[nid]}. Deferred means not taught in this course. If it is taught in less time than the map gives it, list it under 'trimmed' with the minutes it gets.")
    for nid, d in trimmed.items():
        if nid not in taught_in:
            p.append(f"“{nodes.get(nid, {}).get('name', nid)}” is listed as trimmed but no session teaches it. Trimmed means taught in less time; not taught at all means deferred.")
        if not isinstance(d.get("minutes_given"), int) or d["minutes_given"] < 0 or not _txt(d.get("reason")):
            p.append(f"“{nodes.get(nid, {}).get('name', nid)}” is trimmed: give the whole number of minutes it gets and the reason.")
    for nid, n in nodes.items():
        if n.get("role") != "required":
            continue
        if nid not in taught_in:
            if nid in deferred and _txt(deferred[nid].get("reason")) and tc.get("exists") is True:
                continue
            p.append(f"The required topic “{n.get('name')}” ({nid}) is not taught in any session. Teach it before what needs it, or, if the time truly cannot hold it, list it under 'deferred' with the reason AND set time_conflict.exists to true. Never drop a foundation quietly.")
    for nid, n in nodes.items():
        if nid in taught_in and n.get("role") == "required":
            for r in n.get("requires") or []:
                if nodes.get(r, {}).get("role") == "required" and r in taught_in and taught_in[r] > taught_in[nid]:
                    p.append(f"“{n.get('name')}” is taught in session {taught_in[nid]}, before what it needs, “{nodes[r].get('name')}”, in session {taught_in[r]}.")
                elif nodes.get(r, {}).get("role") == "required" and r not in taught_in:
                    why = "is deferred, so it is not available" if r in deferred else "no session teaches"
                    p.append(f"“{n.get('name')}” is taught in session {taught_in[nid]}, but it needs “{nodes[r].get('name')}”, which {why}. Defer what depends on it too, teach the prerequisite, or declare the conflict for the team to resolve.")
    pol = project_policy(plan)
    projects = [x for x in out.get("projects") or [] if isinstance(x, dict)]
    ids = [x.get("id") for x in projects]
    if len(set(ids)) != len(ids) or any(not _txt(i) for i in ids):
        p.append("Every project needs its own id.")
    minor, major = [x for x in projects if x.get("kind") == "minor"], [x for x in projects if x.get("kind") == "major"]
    if len(minor) < pol["minor"] and not tc.get("exists"):
        p.append(f"A course this size holds at least {pol['minor']} minor project{'s' if pol['minor'] != 1 else ''}. The outline has {len(minor)}.")
    if len(major) < pol["major"] and not tc.get("exists"):
        p.append(f"A course this size holds a major project that integrates the outcomes. The outline has {len(major)}.")
    for x in projects:
        t = f"Project “{_txt(x.get('title'))[:50]}”"
        av = x.get("available_after_session")
        if not isinstance(av, int) or not 1 <= av <= n_s:
            p.append(f"{t} needs 'available_after_session' between 1 and {n_s}: the session by which everything it needs has been taught.")
            continue
        for nid in x.get("nodes_required") or []:
            if nid not in nodes:
                p.append(f"{t} needs {nid}, which is not in the map.")
            elif nodes[nid].get("role") == "required" and (nid not in taught_in or taught_in[nid] > av):
                p.append(f"{t} needs “{nodes[nid].get('name')}”, but it is {'not taught in any session' if nid not in taught_in else f'taught in session {taught_in[nid]}, after the project becomes available in session {av}'}. No project may depend on something not yet taught.")
        hosted = [h for h in x.get("hosted_in_sessions") or [] if isinstance(h, int)]
        if any(h < av or h > n_s for h in hosted):
            p.append(f"{t} is worked on in a session before it is available (session {av}) or beyond session {n_s}.")
        if not [q for q in x.get("milestones") or [] if isinstance(q, dict) and _txt(q.get("what"))]:
            p.append(f"{t} has no milestones.")
        if not _txt(x.get("deliverable")):
            p.append(f"{t} does not say what learners hand in.")
    ind = plan.get("independent")
    weeks = int(plan.get("weeks") or 1) if plan.get("weekly") else 1
    per = int((ind or {}).get("perWeekMinutes") or 0)
    if ind:
        tot = {}
        for i, s in enumerate(sessions, 1):
            iw = s.get("independent_work") or {}
            tot[week_of(plan, i)] = tot.get(week_of(plan, i), 0) + (iw.get("minutes") if isinstance(iw.get("minutes"), int) else 0)
        for w in range(1, weeks + 1):
            if tot.get(w, 0) != per:
                p.append(f"Week {w}'s independent work adds up to {tot.get(w, 0)} minutes. The brief gives exactly {per} each week. Set it with 'independent_work' in that week's sessions.")
    # Every project minute is placed: a live minute in a named meeting, an independent minute in a named week. Each budget is held separately and nothing is counted in both.
    live_by_session, ind_by_week = {}, {}
    for x in projects:
        t = f"Project “{_txt(x.get('title'))[:50]}”"
        ms = [q for q in x.get("milestones") or [] if isinstance(q, dict)]
        lv = ix = 0
        for q in ms:
            l_, i_ = q.get("live_minutes"), q.get("independent_minutes")
            if not isinstance(l_, int) or not isinstance(i_, int) or l_ < 0 or i_ < 0:
                p.append(f"{t}: every milestone needs live_minutes and independent_minutes as whole numbers, 0 or more.")
                break
            sn = q.get("session")
            if not isinstance(sn, int) or not 1 <= sn <= n_s:
                p.append(f"{t}: a milestone names session {sn}, which does not exist.")
                break
            if isinstance(x.get("available_after_session"), int) and sn < x["available_after_session"]:
                p.append(f"{t}: a milestone is placed in session {sn}, before the project is available (session {x['available_after_session']}).")
            lv += l_
            ix += i_
            live_by_session[sn] = live_by_session.get(sn, 0) + l_
            if i_:
                ind_by_week[week_of(plan, sn)] = ind_by_week.get(week_of(plan, sn), 0) + i_
        mm = x.get("minutes") or {}
        if ms and (lv != mm.get("live") or ix != mm.get("independent")):
            p.append(f"{t}: its milestones place {lv} live and {ix} independent minutes, but the project says {mm.get('live')} and {mm.get('independent')}. They must agree.")
        if ix and not ind:
            p.append(f"{t} puts {ix} minutes in independent work, but the brief has no independent time.")
    for sn, m_ in live_by_session.items():
        if 1 <= sn <= n_s and m_ > plan["minutes"][sn - 1]:
            p.append(f"Session {sn} is {plan['minutes'][sn - 1]} minutes, but projects place {m_} live minutes in it.")
    setup = out.get("setup") or {}
    setup_min = setup.get("minutes") if isinstance(setup.get("minutes"), int) else 0
    if setup_min and setup.get("counted_in") == "independent_week_1":
        ind_by_week[1] = ind_by_week.get(1, 0) + setup_min
    if setup_min and setup.get("counted_in") == "separate_extra" and not tc.get("exists"):
        p.append(f"Setup of {setup_min} minutes outside the brief's hours is extra time. Declare it under time_conflict so the team can approve it, and say the new total.")
    if setup_min and setup.get("counted_in") not in ("independent_week_1", "separate_extra", "inside_meetings"):
        p.append("Setup says how many minutes it takes but not where they are counted: independent_week_1, inside_meetings or separate_extra.")
    for w, m_ in ind_by_week.items():
        if m_ > per:
            p.append(f"Week {w}'s independent budget is {per} minutes, but projects{' and setup' if w == 1 and setup_min else ''} place {m_} independent minutes in it.")
    acct = accounting(plan)
    need = sum((trimmed[n["id"]]["minutes_given"] if n["id"] in trimmed and isinstance(trimmed[n["id"]].get("minutes_given"), int) else int(n.get("est_minutes") or 0))
               for n in nodes.values() if n.get("role") == "required" and n["id"] in taught_in)
    proj_min = 0  # a project's minutes are placed inside the meetings and independent weeks that hold the topics; they are not a second copy of them
    if need > acct["combinedMinutes"] * 0.9 and not tc.get("exists"):
        p.append(f"The topics taught need about {need} minutes at the depth given. The brief holds {acct['combinedMinutes']}, and about a tenth of that goes on setup, feedback and breaks. Say so under time_conflict, with honest options: more time, prerequisite work before the course, or a narrower outcome.")
    if tc.get("exists") is True and (not _txt(tc.get("explanation")) or len([o for o in tc.get("options") or [] if isinstance(o, dict) and _txt(o.get("label"))]) < 2):
        p.append("A time conflict needs an explanation and at least two options the team can choose between.")
    return p


def coverage(out: dict, m: dict) -> dict:
    """What the approved outline covers, worked out from the outline itself and never taken on trust."""
    nodes = {n["id"]: n for n in m.get("nodes") or []}
    rows, taught = [], {}
    for i, s in enumerate(out.get("sessions") or [], 1):
        for nid in s.get("teaches") or []:
            taught.setdefault(nid, i)
    practised = {}
    for i, s in enumerate(out.get("sessions") or [], 1):
        for nid in (s.get("practises") or []) + (s.get("teaches") or []):
            practised.setdefault(nid, []).append(i)
    for nid, n in nodes.items():
        rows.append({"node": nid, "name": n.get("name"), "role": n.get("role"), "kind": n.get("kind"), "taughtInSession": taught.get(nid), "practisedInSessions": practised.get(nid, []),
                     "usedByProjects": [x.get("id") for x in out.get("projects") or [] if nid in (x.get("nodes_required") or [])]})
    return {"rows": rows, "deferred": out.get("deferred") or [],
            "requiredNotTaught": [r["name"] for r in rows if r["role"] == "required" and r["taughtInSession"] is None]}


# ---------------------------------------------------------------- research

def plan_batches(m: dict) -> tuple[list, list]:
    """Node batches for research, in teaching order, and the names left unresearched because of the cap. Nothing is dropped silently."""
    d = derive_map(m)
    by = {n["id"]: n for n in d["nodes"]}
    want = [by[i] for i in d["derived"]["order"] if by[i].get("role") in ("required", "optional") and by[i].get("needs_evidence", True)]
    kept, left = want[:MAX_RESEARCH_NODES], want[MAX_RESEARCH_NODES:]
    batches = [{"key": "approach", "nodes": []}]
    for i in range(0, len(kept), BATCH_SIZE):
        batches.append({"key": f"nodes-{i // BATCH_SIZE + 1}", "nodes": [n["id"] for n in kept[i:i + BATCH_SIZE]]})
    return batches, [n["name"] for n in left]


def _flat(t) -> str:
    return re.sub(r"[\s ]+", " ", re.sub(r"[^\w\s]", "", str(t or "").lower())).strip()


def quote_found(quote: str, text: str) -> bool | None:
    """Is the quoted wording in what the fetch really returned? None when there is no quote to check."""
    q = _flat(quote)
    if len(q) < 8:
        return None
    return q in _flat(text)


def merge_research(parts: list) -> dict:
    """One research record from several batches. The same page found twice is one source that serves several topics."""
    sources, seen = [], {}
    searches, opened, asked, not_opened, questions = [], [], [], [], []
    findings = {}
    combo = None
    for part in parts:
        for s in part.get("sources") or []:
            key = (norm_url(s["url"]), norm(s.get("claim")))
            if key in seen:
                t = seen[key]
                t["node_ids"] = list(dict.fromkeys((t.get("node_ids") or []) + (s.get("node_ids") or [])))
                if t.get("fetch") != "retrieved" and s.get("fetch") == "retrieved":
                    ids = t["node_ids"]
                    t.clear()
                    t.update(dict(s, node_ids=ids))
                continue
            # The same page cited for a different claim is a separate source: its quote and strength were judged for that claim only.
            seen[key] = dict(s)
            sources.append(seen[key])
        searches += part.get("searches") or []
        opened += [u for u in part.get("pagesOpened") or [] if u not in opened]
        asked += part.get("pagesAskedFor") or []
        not_opened += [n for n in part.get("not_opened") or [] if n.get("url") not in {x.get("url") for x in not_opened}]
        questions += [q for q in part.get("open_questions") or [] if q not in questions]
        for f in part.get("node_findings") or []:
            cur = findings.get(f.get("node"))
            rank = {"supported": 2, "partly": 1, "none_found": 0}
            if not cur or rank.get(f.get("status"), 0) > rank.get(cur.get("status"), 0):
                findings[f.get("node")] = f
        if part.get("combination_evidence") and (part.get("combination_evidence") or {}).get("status") != "not_applicable" or combo is None:
            combo = part.get("combination_evidence") or combo
    for i, s in enumerate(sources):
        s["id"] = f"S{i + 1}"
    return {"sources": sources, "searches": searches, "pagesOpened": opened, "pagesAskedFor": asked, "not_opened": not_opened, "open_questions": questions, "node_findings": list(findings.values()),
            "combination_evidence": combo or {"status": "not_applicable", "note": ""}}


def claim_key(s: dict) -> str:
    """One key for one claim on one page. A reviewer's verdict belongs to this and to nothing broader."""
    return norm_url(s.get("url", "")) + "|" + norm(s.get("claim"))


def source_effect(s: dict, verdict: str) -> dict:
    """What a source reviewer's judgement does to a source. It can only lower a source, never raise one."""
    s = dict(s)
    if verdict == "no":
        s["strength"] = "background"
        s["limits"] = (_txt(s.get("limits")) + " The source reviewer found that this page does not support the claim attached to it.").strip()
    elif verdict in ("cannot_tell", None) and s.get("strength") == "direct":
        s["strength"] = "partial"
        s["auditUnresolved"] = True
        s["limits"] = (_txt(s.get("limits")) + " The source audit could not tell whether this page supports the claim, so it is not counted as support.").strip()
    elif verdict == "partly" and s.get("strength") == "direct":
        s["strength"] = "partial"
        s["limits"] = (_txt(s.get("limits")) + " The source reviewer found that this page supports only part of the claim.").strip()
    return s


# ---------------------------------------------------------------- checks on projects and assets

def check_project(out: dict, unit: dict, m: dict, taught_in: dict, source_ids) -> list:
    p = []
    for k in ("title", "purpose", "learner_brief", "feedback_route", "revision_route", "example_or_solution_guidance"):
        if not _txt(out.get(k)):
            p.append(f"The project has no {k.replace('_', ' ')}.")
    nodes = {n["id"]: n for n in m.get("nodes") or []}
    if not out.get("deliverables"):
        p.append("The project does not say what learners hand in.")
    ms = [q for q in out.get("milestones") or [] if isinstance(q, dict)]
    av = unit.get("available_after_session") or 1
    if len(ms) < 2:
        p.append("A project needs at least two milestones, so that learners are not left alone with it until the deadline.")
    for q in ms:
        if not _txt(q.get("what")) or not _txt(q.get("check")):
            p.append("Every milestone says what learners do and how it is checked.")
            break
        if isinstance(q.get("session"), int) and q["session"] < av:
            p.append(f"A milestone is set in session {q['session']}, before the project is available (session {av}).")
    for q in out.get("prerequisites") or []:
        nid = q.get("node")
        if nid in nodes and nodes[nid].get("role") == "required" and (nid not in taught_in or taught_in[nid] > av):
            p.append(f"The project lists “{nodes[nid].get('name')}” as needed, but it is not taught by session {av}.")
    for nid in unit.get("nodes_required") or []:
        if nid in nodes and nodes[nid].get("role") == "required" and nid not in [q.get("node") for q in out.get("prerequisites") or []]:
            p.append(f"The outline says this project needs “{nodes[nid].get('name')}”, but the brief does not list it as a prerequisite.")
    rub = out.get("rubric") or []
    if len(rub) < 3:
        p.append("The rubric needs at least three criteria.")
    for r in rub:
        if len([lv for lv in r.get("levels") or [] if _txt(lv.get("descriptor"))]) < 3:
            p.append(f"The rubric criterion “{_txt(r.get('criterion'))[:40]}” needs at least three levels, each described by what the work looks like.")
            break
    t = out.get("time") or {}
    planned = unit.get("minutes") or {}
    if isinstance(planned, dict) and (t.get("live") != planned.get("live") or t.get("independent") != planned.get("independent")):
        p.append(f"The time must be the approved {planned.get('live', 0)} minutes live and {planned.get('independent', 0)} independent.")
    msum = sum(q.get("minutes") for q in ms if isinstance(q.get("minutes"), int))
    if isinstance(t.get("live"), int) and isinstance(t.get("independent"), int) and msum != t["live"] + t["independent"]:
        p.append(f"The milestones add up to {msum} minutes. The project's time is {t['live'] + t['independent']}.")
    strength = source_ids if isinstance(source_ids, dict) else {}
    for c in out.get("claims") or []:
        bad = [s for s in c.get("sources") or [] if s not in source_ids]
        if bad:
            p.append(f"A claim cites {', '.join(bad)}, which is not in the list of sources.")
        if c.get("type") == "fact" and not (c.get("sources") or []):
            p.append(f"“{_txt(c.get('text'))[:60]}” is marked as a fact but cites no source.")
        elif c.get("type") == "fact" and c.get("support") in ("partly", "not_from_source"):
            p.append(f"“{_txt(c.get('text'))[:60]}” is marked as a fact, but you say the source states it only in part or not at all. Mark it uncertain or hypothesis, or split off what the source states.")
        elif c.get("type") == "fact" and not bad and strength and not any(strength.get(s) == "direct" for s in c["sources"]):
            p.append(f"“{_txt(c.get('text'))[:60]}” is marked as a fact, but every source it cites is recorded as supporting it only in part. Mark it uncertain.")
    if [a for a in out.get("inputs") or [] if isinstance(a, dict) and a.get("kind") in ("solution", "rubric")]:
        p.append("'inputs' is what learners are given. A solution or a rubric goes under solution_assets or in the rubric, never in inputs.")
    return p


def check_assets(assets: list, where: str) -> list:
    """Each asset is complete on its face. Whether it runs is settled separately, by running it."""
    p, seen = [], set()
    for a in assets or []:
        nm = _txt(a.get("name"))
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$", nm) or nm.startswith("_"):
            p.append(f"{where}: every asset needs a plain file name, like clean_air.csv: letters, numbers, dots, dashes, at most 80 characters, no folders, no spaces.")
            continue
        if nm in seen:
            p.append(f"{where}: two assets are called {nm}.")
        seen.add(nm)
        if not _txt(a.get("content")):
            p.append(f"{where}: {nm} is listed but its content is empty. Write the whole file out.")
        if a.get("kind") == "dataset":
            if a.get("provenance") not in ("public_source", "synthetic_practice", "authored"):
                p.append(f"{where}: {nm} must say where it comes from: public_source, synthetic_practice or authored.")
            if a.get("provenance") == "public_source" and not _txt(a.get("source_id")):
                p.append(f"{where}: {nm} says it comes from a public source but names none. Cite a listed source id, or mark it synthetic_practice.")
            problem = dataset_problem(a.get("content"), nm)
            if problem:
                p.append(f"{where}: {problem}")
    return p


def _numbers(content: str, limit: int = 14) -> list:
    """Distinct numeric values from the data rows (not the header), read as CSV fields so that 2001,412 is two numbers."""
    seen = []
    try:
        rows = list(csv.reader(io.StringIO(str(content or ""))))[1:]
    except csv.Error:
        rows = [str(content or "").splitlines()[1:]]
    for row in rows:
        for f in row:
            f = str(f).strip().replace(",", "")
            if re.fullmatch(r"-?\d+(\.\d+)?", f) and len(f.replace("-", "").replace(".", "")) >= 3 and f not in seen:
                seen.append(f)
            if len(seen) >= limit:
                return seen
    return seen


def _flat_numbers(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(text or ""))


def origin_checks(assets: list, source_texts: dict) -> list:
    """A dataset that says it is an extract of a public source is checked against what that page really returned.

    This cannot show the data is right. It can show it is invented: values that appear nowhere in the page are not an extract of it.
    """
    out = []
    for a in assets or []:
        if a.get("kind") != "dataset" or a.get("provenance") != "public_source":
            continue
        text = source_texts.get(_txt(a.get("source_id"))) or ""
        nums = _numbers(a.get("content"))
        rec = {"name": a.get("name"), "kind": "dataset", "check": "origin", "assetPrint": asset_print(a)}
        if not text:
            rec.update(level="origin_failed", reason="It says it comes from a public source, but that page never reached the AI, so it cannot be shown to be an extract of it.")
        elif len(nums) < 4:
            rec.update(level="origin_unverified", reason="Too few distinct numbers to compare with the page.")
        else:
            flat = _flat_numbers(text)
            hit = [n for n in nums if re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", flat)]
            # Numbers that appear in a page's text are not provenance: years, counts and coincidences appear anywhere. This can only show that a dataset is NOT what it says.
            rec.update(hit=len(hit), of=len(nums), level="origin_unverified" if len(hit) / len(nums) >= 0.25 else "origin_failed",
                       reason=f"{len(hit)} of {len(nums)} values also appear in the text the tool returned. That is a rough check and does not show the file is a true extract of the original. It is NOT verified as original data." if len(hit) / len(nums) >= 0.25
                       else f"{len(hit)} of {len(nums)} values appear in the text the tool returned. That is too few for an extract of it.")
        out.append(rec)
    return out


def dataset_problem(text: str, name: str) -> str:
    if not name.lower().endswith(".csv"):
        return ""
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as e:
        return f"{name} is not readable as CSV: {e}."
    if len(rows) < 3:
        return f"{name} has fewer than two data rows."
    # Uneven rows are allowed: they may be the point of a cleaning exercise. A person judges that, not this check.
    return ""


# ---------------------------------------------------------------- running supplied code

def _interpreters() -> list:
    from . import storage
    cands = [str(storage.data_root() / ".venv" / "bin" / "python"), "/opt/homebrew/bin/python3.14", "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3", sys.executable]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen and Path(c).exists():
            seen.add(c)
            out.append(c)
    return out


def top_imports(code: str) -> set | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            mods.add(n.module.split(".")[0])
    return mods


_can_import_cache: dict = {}


_usable_cache: dict = {}


def usable(py: str) -> bool:
    """Can this interpreter run a line of code at all? One that exits with an error (an unaccepted licence, a broken install) or hangs is not usable."""
    if py not in _usable_cache:
        try:
            r = subprocess.run([py, "-c", "print('loom-probe-ok')"], capture_output=True, text=True, timeout=20)
            _usable_cache[py] = r.returncode == 0 and r.stdout.strip() == "loom-probe-ok"
        except (OSError, subprocess.SubprocessError):
            _usable_cache[py] = False
    return _usable_cache[py]


def can_import(py: str, mods: set) -> set | None:
    """The modules of `mods` that interpreter `py` cannot import, or None when the interpreter cannot be used or answered wrongly.

    A probe that fails, times out or prints nothing is never read as "nothing is missing".
    """
    if not usable(py):
        return None
    need = sorted(m for m in mods if m not in getattr(sys, "stdlib_module_names", set()))
    if not need:
        return set()
    key = (py, tuple(need))
    if key not in _can_import_cache:
        try:
            r = subprocess.run([py, "-c", "import importlib.util,sys\nprint('loom-probe-ok:' + ','.join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))", *need], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        line = r.stdout.strip()
        if r.returncode != 0 or not line.startswith("loom-probe-ok:"):
            return None
        _can_import_cache[key] = set(x for x in line[len("loom-probe-ok:"):].split(",") if x)
    return _can_import_cache[key]


SANDBOX = "/usr/bin/sandbox-exec"


def sandbox_available() -> bool:
    if not Path(SANDBOX).exists():
        return False
    try:
        return subprocess.run([SANDBOX, "-p", "(version 1)(allow default)(deny network*)", "/usr/bin/true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _sb(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def run_python(code: str, files: dict, timeout: int = 30) -> dict:
    """Run supplied code on supplied files, in a restricted sandbox.

    The sandbox denies the network, any write outside the run's own temporary folder, any read of file contents under /Users, /tmp and the system's temporary folders except the run's own folder,
    the interpreter's own libraries and the user-level packages, starting other programs, forking, contacting system services
    (which is how a program could otherwise ask the system to start something outside the sandbox), and signalling other processes.
    Output and file size are capped. The sandbox is macOS's own and is a barrier, not a proof: it is judged by the tests in
    tests/server/test_pipeline.py, and the code it runs was written by a model that has read web pages.

    Returns {state: ran|failed|not_run, ...}. If the sandbox is not there, nothing is run: it is reported as not run, never run unprotected.
    """
    mods = top_imports(code)
    if mods is None:
        return {"state": "failed", "reason": "The code is not valid Python: it does not parse.", "output": ""}
    if not sandbox_available():
        return {"state": "not_run", "reason": "No sandbox is available on this computer, so the code was not run.", "output": ""}
    py = None
    missing_all = {}
    for cand in _interpreters():
        miss = can_import(cand, mods)
        if miss is None:
            continue  # unusable here: never chosen, never counted as a pass
        if not miss:
            py = cand
            break
        missing_all[cand] = miss
    if py is None:
        need = sorted(set.intersection(*missing_all.values())) if missing_all else []
        if not missing_all:
            return {"state": "not_run", "reason": "This computer has no Python interpreter that can run code, so the code was not run. This says nothing about whether the code is right.", "output": ""}
        return {"state": "not_run", "reason": f"This computer has no Python that can import {', '.join(need) or 'what the code needs'}, so the code was not run. This says nothing about whether the code is right.", "output": ""}
    import resource
    import signal
    with tempfile.TemporaryDirectory(prefix="loom-run-") as tmp:
        tmp = str(Path(tmp).resolve())
        for name, content in files.items():
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$", name) or name.startswith("_asset") or name in ("_stdout.txt", "_stderr.txt"):
                return {"state": "failed", "reason": f"“{name[:40]}” is not a plain file name.", "output": ""}
            (Path(tmp) / name).write_text(content, encoding="utf-8")
        (Path(tmp) / "_asset_under_test.py").write_text(code, encoding="utf-8")
        try:
            base = subprocess.run([py, "-c", "import site;print(site.getuserbase())"], capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            base = ""
        pyreal = str(Path(py).resolve())
        venv = str(Path(py).parent.parent) if ".venv" in py else ""
        readable = [tmp] + ([venv] if venv else []) + ([base] if base and base.startswith("/Users") else [])
        rules = ['(version 1)', '(allow default)', '(deny network*)', '(deny mach-lookup)', '(deny process-fork)', '(deny process-exec*)',
                 '(allow process-exec* (regex #"^/.*/(python[0-9.]*|Python)$"))', '(deny signal (target others))',
                 f'(deny file-write* (require-not (subpath "{_sb(tmp)}")))', '(allow file-write* (literal "/dev/null"))',
                 '(deny file-read* (subpath "/Users") (subpath "/private/var/folders") (subpath "/private/tmp") (subpath "/tmp") (subpath "/Volumes"))', '(allow file-read-metadata (subpath "/Users") (subpath "/private/var/folders"))'] + [f'(allow file-read* (subpath "{_sb(r)}"))' for r in readable]
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp, **({"PYTHONUSERBASE": base} if base else {}), "TMPDIR": tmp, "MPLBACKEND": "Agg", "MPLCONFIGDIR": tmp, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8"}

        def limits():
            os.setsid()
            resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))
            resource.setrlimit(resource.RLIMIT_FSIZE, (20 * 1024 * 1024, 20 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        # The parent keeps the descriptors it opened and reads only from them. It never reopens a path the run could have replaced with a link.
        with open(Path(tmp) / "_stdout.txt", "w+b") as fo, open(Path(tmp) / "_stderr.txt", "w+b") as fe:
            proc = subprocess.Popen([SANDBOX, "-p", " ".join(rules), py, "_asset_under_test.py"], cwd=tmp, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, env=env, preexec_fn=limits)
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)  # nothing the code started is left behind
                except OSError:
                    pass
                proc.wait()

            def tail(f, n):
                size = os.fstat(f.fileno()).st_size
                f.seek(max(0, size - n))
                return f.read(n).decode("utf-8", "replace")
            out, err = tail(fo, 1500), tail(fe, 800)
        made = sorted(q.name for q in Path(tmp).iterdir() if q.name not in files and not q.name.startswith("_"))
        if timed_out:
            return {"state": "failed", "reason": f"The code did not finish in {timeout} seconds.", "output": out, "python": py}
        if proc.returncode != 0:
            return {"state": "failed", "reason": "The code stopped with an error.", "output": out, "error": err, "python": py, "made": made}
        return {"state": "ran", "reason": "", "output": out, "error": err, "python": py, "made": made}


def asset_print(a: dict) -> str:
    """A fingerprint of exactly what was checked: this file's name and these bytes.

    A result carries it so that a check can never be read as applying to a file that has since changed. Editing
    one character gives a different fingerprint and the old result stops matching. This is the fingerprint the
    page builds the same way, so both sides agree about which file a result belongs to.
    """
    from .engine import content_print
    return content_print([str(a.get("name") or ""), str(a.get("content") or "")])


def checks_for(assets: list, results: list) -> list:
    """Only the results that still belong to the files as they are now.

    A result whose checksum no longer matches its file is not shown as a pass or a failure: it is replaced by a
    plain statement that the file changed after it was checked. A changed program never inherits an older run.
    """
    want = {asset_print(a): a for a in assets or []}
    by_name: dict = {}
    for a in assets or []:
        by_name.setdefault(str(a.get("name") or ""), []).append(asset_print(a))
    out = []
    for r in results or []:
        if r.get("assetPrint") and r["assetPrint"] in want:
            out.append(r)
        elif not r.get("assetPrint"):
            out.append(r)  # an older record made before checks carried a fingerprint; left as it was
        elif r.get("name") in by_name:
            out.append({"name": r.get("name"), "kind": r.get("kind"), "check": r.get("check"), "assetPrint": by_name[r["name"]][0],
                        "state": "stale", "level": "not_run", "output": "",
                        "reason": "This file changed after it was checked, so the earlier result no longer applies to it."})
    return out


def run_assets(assets: list, in_hand: list) -> list:
    """Run every asset marked to be run, on the datasets in hand. `in_hand` is assets from earlier in the course.

    A code asset is checked by running it when its `run` says so, and by parsing it when it is a starter with gaps left on purpose.
    """
    files = {}
    for a in (in_hand or []) + (assets or []):
        if a.get("kind") == "dataset" and _txt(a.get("name")) and _txt(a.get("content")):
            files[a["name"]] = a["content"]
    results = []
    for a in assets or []:
        if a.get("kind") not in ("code", "starter", "solution"):
            continue
        rec = {"name": a.get("name"), "kind": a.get("kind"), "check": a.get("run"), "assetPrint": asset_print(a)}
        code = a.get("content") or ""
        if a.get("run") == "run" and not (str(a.get("name") or "").lower().endswith(".py") or "python" in str(a.get("language") or "").lower()):
            rec.update(state="not_run", level="not_run", reason="Only Python can be run here. This file is not Python, so it was not run.", output="")
        elif a.get("run") == "run":
            r = run_python(code, files)
            rec.update(r)
            rec["level"] = "executed" if r["state"] == "ran" else "not_run" if r["state"] == "not_run" else "failed"
        else:
            ok = top_imports(code) is not None
            rec.update(state="ran" if ok else "failed", level="syntax_only" if ok else "failed", reason="" if ok else "The starter is not valid Python even with its gaps.",
                       output="", note="Checked that it parses. A starter has gaps on purpose, so it is not run.")
        results.append(rec)
    return results


def asset_problems(results: list, where: str) -> list:
    return [f"{where}: {r['name']} {r['reason']} Mark it synthetic_practice and say so, or use values that are in the page." for r in results if r.get("level") == "origin_failed"] + [f"{where}: {r['name']} {r.get('reason') or 'did not pass'} {(r.get('error') or '').strip().splitlines()[-1][:200] if r.get('error') else ''}".strip()
            for r in results if r.get("level") == "failed"]
