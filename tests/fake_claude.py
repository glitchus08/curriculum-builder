#!/usr/bin/env python3
"""A stand-in for the Claude command-line tool, used ONLY by automated tests.

It lets the tests rehearse failure, pause and resume without using anyone's subscription. It never runs in normal use:
the server only uses it when LOOM_CLAUDE_BIN points here. Its answers are obviously artificial and are marked TEST DOUBLE.

FAKE_CLAUDE_PLAN names a JSON file: {"calls": 0, "fail": {"3": "limit"}, "bad_minutes_on": [2]}
  "fail" maps a call number to: limit, overage, api_key, auth, crash, hang, nonsense.
"""
import json
import os
import re
import sys
import time

args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("0.0.0 (test double)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "test"}))
    sys.exit(0)

prompt = sys.stdin.read()
plan_file = os.environ.get("FAKE_CLAUDE_PLAN")
plan = {"calls": 0, "fail": {}}
if plan_file and os.path.exists(plan_file):
    plan.update(json.load(open(plan_file)))
plan["calls"] += 1
n = plan["calls"]
plan.setdefault("log", []).append({"n": n, "stage": (re.search(r'<task stage="(\w+)"', prompt) or [None, "?"])[1], "repair": "DID NOT PASS LOOM'S CHECKS" in prompt, "tools": args[args.index("--tools") + 1] if "--tools" in args else None,
                                   "has_api_env": any(k.startswith("ANTHROPIC") for k in os.environ), "has_claude_env": any(k.startswith("CLAUDE") for k in os.environ),
                                   "session": (re.search(r'<task [^>]*\bsession="(\d+)"', prompt) or [None, None])[1], "carried": sorted(set(re.findall(r"TEST DOUBLE handout made in session (\d+)", prompt))),
                                   "saw_teacher_notes": "Watch for confusion." in (re.search(r"<(sessions_already_written|other_sessions)>.*?</\1>", prompt, re.S) or [""])[0], "continuity_rule": "CONTINUITY" in prompt,
                                   "marks": [m for m in (plan.get("watch") or []) if m in prompt]})
if plan_file:
    json.dump(plan, open(plan_file, "w"))
mode = (plan.get("fail") or {}).get(str(n))


def emit(o):
    print(json.dumps(o), flush=True)


def attr(name, default=None):
    m = re.search(r'<task [^>]*\b' + name + r'="([^"]*)"', prompt)
    return m.group(1) if m else default


def block(tag):
    m = re.search(r"<" + tag + r">\n(.*?)\n</" + tag + r">", prompt, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except ValueError:
        return m.group(1) if m else None


emit({"type": "system", "subtype": "init", "model": "test-double", "apiKeySource": "ANTHROPIC_API_KEY" if mode == "api_key" else "none", "tools": []})
emit({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected" if mode == "limit" else "allowed", "resetsAt": int(time.time()) + 3600, "rateLimitType": "five_hour", "overageStatus": "rejected", "isUsingOverage": mode == "overage"}})
if mode == "hang":
    time.sleep(600)
if mode == "crash":
    sys.stderr.write("test double: simulated crash\n")
    sys.exit(3)
if mode == "limit":
    emit({"type": "result", "subtype": "success", "is_error": True, "result": "You've hit your session limit · resets 3pm", "num_turns": 1, "usage": {}, "modelUsage": {}})
    sys.exit(1)
if mode == "auth":
    emit({"type": "result", "subtype": "success", "is_error": True, "result": "Invalid API key · Please run /login", "num_turns": 1, "usage": {}, "modelUsage": {}})
    sys.exit(1)
if mode == "nonsense":
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "I would rather write a poem.", "num_turns": 1, "usage": {}, "modelUsage": {}})
    sys.exit(0)

stage = attr("stage")
brief = block("brief") or {}
topics = brief.get("topics") or ["the topic"]
TAG = "TEST DOUBLE"


def activity(kind, title, minutes):
    return {"kind": kind, "title": f"{TAG} {title}", "goal": f"{TAG} goal for {title}", "minutes": minutes, "instructions": [] if kind == "setup" else ["Step one.", "Step two."], "materials": ["Paper"], "handout": "", "worked_example": "",
            "teacher": [] if kind == "setup" else ["Watch for confusion."], "misconceptions": [], "success": ["The work shows it."]}


def session(title, minutes, session_topics, wrong=False, number=0):
    parts = [("setup", "Set up", 5), ("try", "First attempt", 0), ("feedback", "Feedback in pairs", 5), ("revise", "Improve it", 5)]
    rest = minutes - 15 + (5 if wrong else 0)
    acts = [activity(k, t, m or rest) for k, t, m in parts]
    if number:
        acts[1]["handout"] = f"{TAG} handout made in session {number}"
    return {"title": title, "outcome": f"{TAG} outcome using {', '.join(session_topics)}", "serves": f"{TAG} serves the course outcome", "prerequisites": [{"name": "Basic reading", "support": "Pair them up."}], "prerequisites_note": "",
            "contributions": [{"topic": t, "gives": f"{TAG} {t} gives a constraint"} for t in session_topics], "preparation": {"minutes": 20, "steps": ["Print the task sheet."]}, "activities": acts, "success_criteria": ["Criterion one is visible.", "Criterion two is visible."],
            "application_check": {"when": "One week later", "task": f"{TAG} a changed task", "looks_for": ["Done without help"]},
            "claims": [{"text": f"{TAG} a teaching judgement", "type": "hypothesis", "sources": [], "support": "not_from_source", "note": ""}, {"text": f"{TAG} a fact from a source", "type": "fact", "sources": ["S1"], "support": "stated_by_source", "note": ""}], "assumptions": ["A room with tables."]}


CODE_OK = "import csv\nrows = list(csv.DictReader(open('data.csv')))\nprint('rows', len(rows))\n"


def v2_out():
    """Answers for the expanded pipeline. Artificial, marked TEST DOUBLE, and driven by the plan file so failures can be rehearsed."""
    variant = plan.get("variant") or {}
    if stage == "map":
        nodes = [
            {"id": "N1", "name": topics[0], "kind": "requested", "role": "required", "why_needed": "", "needed_by": ["OUTCOME"], "requires": ["N3"], "depth": "applied", "entry_reached": True, "below_entry": "", "est_minutes": 60, "needs_evidence": True, "research_questions": ["q1"]},
            {"id": "N2", "name": topics[1] if len(topics) > 1 else "Second", "kind": "requested", "role": "required", "why_needed": "", "needed_by": ["OUTCOME"], "requires": ["N3"], "depth": "working", "entry_reached": True, "below_entry": "", "est_minutes": 40, "needs_evidence": True, "research_questions": ["q2"]},
            {"id": "N3", "name": "Reading a table", "kind": "foundation", "role": "required", "why_needed": f"{TAG} both topics start from a table", "needed_by": ["N1", "N2"], "requires": ["N4"], "depth": "working", "entry_reached": True, "below_entry": "", "est_minutes": 30, "needs_evidence": True, "research_questions": ["q3"]},
            {"id": "N4", "name": "Files and folders", "kind": "foundation", "role": "already_known", "why_needed": f"{TAG} learners can already open a file", "needed_by": ["N3"], "requires": [], "depth": "awareness", "entry_reached": True, "below_entry": "", "est_minutes": 10, "needs_evidence": False, "research_questions": []},
        ]
        v = variant.get("map")
        if v == "cycle" and "DID NOT PASS" not in prompt:
            nodes[3].update(role="required", requires=["N3"], est_minutes=10)
        if v == "orphan" and "DID NOT PASS" not in prompt:
            nodes.append({"id": "N5", "name": "Unrelated trivia", "kind": "subtopic", "role": "required", "why_needed": "Interesting.", "needed_by": [], "requires": [], "depth": "awareness", "entry_reached": True, "below_entry": "", "est_minutes": 20, "needs_evidence": False, "research_questions": []})
        if v == "gap":
            nodes[2].update(entry_reached=False, below_entry=f"{TAG} how a computer stores numbers")
        return {"nodes": nodes, "outcome_needs": [{"capability": "read a table", "nodes": ["N3"]}], "assumed_entry": ["can open a file"], "stop_reason": f"{TAG} reached the entry level", "unresolved": []}
    if stage == "foundation_review":
        add = [{"name": "Counting rows", "kind": "foundation", "why_needed": f"{TAG} reviewer says it is missing", "needed_by": ["N1"], "requires": [], "est_minutes": 15}] if variant.get("fr") == "missing" else []
        return {"verdict": "gaps" if add else "sound", "summary": f"{TAG} foundations", "missing_foundations": add, "unneeded": [], "ordering_problems": [], "depth_problems": [], "duplicates": []}
    if stage == "research" and "ROLE: You are the course's researcher" in prompt:
        b = attr("batch", "approach")
        nd = block("topics_to_research") or []
        ids = [n["id"] for n in nd]
        url = f"https://example.org/{b}"
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": f"{b} search"}}]}})
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "WebFetch", "input": {"url": url, "prompt": "read"}}]}})
        body = "A table has rows and columns. Each row is one record and each column one measurement. This page states it plainly for beginners."
        emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": body}]}]}})
        good_quote = "each row is one record" if variant.get("quote") != "bad" else "words that the page never said at all"
        srcs = [{"title": f"{TAG} {b} source", "url": url, "publisher": "Example", "year": "2024", "kind": "textbook_or_reference", "topic": topics[0], "node_ids": ids, "claim": f"{TAG} claim {b}", "finding": "A table has rows.", "quote": good_quote, "strength": "direct", "limits": "", "subject_version": "2024", "authors": "The Example Authors", "published": "2024-01-05", "version_or_edition": "2nd", "identifier": "", "role": variant.get("role") or "original_contribution", "lineage": []}]
        if b == "nodes-1" and variant.get("reuse"):
            srcs.append({"title": f"{TAG} approach page reused", "url": "https://example.org/approach", "publisher": "Example", "year": "2024", "kind": "other", "topic": "teaching approach", "node_ids": ids, "claim": "reused claim", "finding": "x", "quote": "", "strength": "direct", "limits": "", "subject_version": ""})
        return {"sources": srcs, "node_findings": [{"node": i, "status": "supported", "summary": f"{TAG} covered", "limits": ""} for i in ids], "not_opened": [], "open_questions": [], "combination_evidence": {"status": "weak", "note": f"{TAG} note"}}
    if stage == "source_review":
        srcs = block("sources") or []
        no = variant.get("sr_no") or []
        asks = [{"node": "N3", "question": f"{TAG} what is a table?", "why": "gap"}] if variant.get("sr") == "targeted" and "may not ask for more research" not in prompt else []
        return {"verdict": "concerns", "summary": f"{TAG} audit", "sources": [{"id": x["id"], "supports_claim": "no" if x["id"] in no else "yes", "reason": f"{TAG} reason"} for x in srcs], "conflicts": [], "node_gaps": [], "targeted_research": asks}
    if stage == "outline" and "<topic_map>" in prompt:
        tm = block("time") or {}
        meetings = tm.get("live_meetings") or [60, 60, 60, 60]
        per = tm.get("independent_minutes_per_week") or 0
        k = tm.get("meetings_per_week") or 1
        n = len(meetings)
        rq = [x for x in (block("topic_map") or {}).get("nodes", []) if x.get("role") == "required"]
        order, left = [], list(rq)
        while left:  # teaching order: a topic after what it requires
            ready = [x for x in left if not [r for r in x.get("requires") or [] if r in {y["id"] for y in left}]] or left[:1]
            order.append(ready[0]["id"])
            left.remove(ready[0])
        teaches = [([order[i]] if i < len(order) else []) if i < n - 1 else order[n - 1:] for i in range(n)]
        if variant.get("outline") == "order" and "DID NOT PASS" not in prompt:
            teaches = [["N1"], ["N3"], ["N2"], []]
        sessions = []
        for i in range(n):
            sessions.append({"title": f"{TAG} session {i + 1}", "outcome": f"{TAG} learners can do part {i + 1}", "serves": "step", "topics": list(topics), "contributions": [{"topic": t, "gives": f"{TAG} {t} gives a method"} for t in topics],
                             "builds_on": [i] if i else [], "key_task": f"{TAG} X to Y", "evidence_of_learning": f"{TAG} Y", "teaches": teaches[i], "practises": [], "independent_work": {"minutes": per // k if per else 0, "tasks": ["task"] if per else []}})
        projects = [
            {"id": "P1", "kind": "minor", "title": f"{TAG} minor project", "purpose": "practise", "nodes_required": ["N3"], "available_after_session": 2, "hosted_in_sessions": [3], "milestones": [{"session": 3, "what": "draft", "live_minutes": 20, "independent_minutes": 20}], "deliverable": "a table", "minutes": {"live": 20, "independent": 20}},
            {"id": "P2", "kind": "major", "title": f"{TAG} capstone", "purpose": "integrate", "nodes_required": ["N1", "N2", "N3"], "available_after_session": 3, "hosted_in_sessions": [n], "milestones": [{"session": n, "what": "hand in", "live_minutes": 30, "independent_minutes": 40}], "deliverable": "a report", "minutes": {"live": 30, "independent": 40}}]
        if variant.get("outline") == "noprojects" or variant.get("noprojects"):
            projects = []
        tc = {"exists": False, "explanation": "", "options": []}
        if variant.get("outline") == "conflict" or variant.get("conflict"):
            tc = {"exists": True, "explanation": f"{TAG} the map needs more than the time", "options": [{"label": "More time", "effect": "add a week"}, {"label": "Narrower outcome", "effect": "drop the capstone"}]}
        return {"course_outcome": brief.get("outcome", ""), "final_evidence": f"{TAG} a report", "feasibility": {"fits": True, "concern": ""}, "sessions": sessions,
                "integration": {"status": "partly", "reason": f"{TAG} reason", "joining_task": ""}, "projects": projects, "deferred": [], "trimmed": [], "setup": {"minutes": 0, "counted_in": "none", "what": ""}, "time_conflict": tc, "pathway_note": "", "assumptions": [f"{TAG} assumption"]}
    if stage == "lineage":
        pages = block("pages") or []
        out = []
        for x in pages:
            k = x.get("key")
            if variant.get("lineage_none"):
                out.append({"key": k, "relationships": [], "origin_of_its_own_subject": "unknown", "note": f"{TAG} the page states no relationship"})
            elif variant.get("lineage_unquoted"):
                out.append({"key": k, "relationships": [{"relation": "extended", "earlier_work": "An earlier work",
                    "earlier_work_identifier": "", "what_changed": "something", "words_that_show_it": "", "limits": ""}],
                    "origin_of_its_own_subject": "names_an_earlier_origin", "note": ""})
            else:
                out.append({"key": k, "relationships": [{"relation": "corrected", "earlier_work": "The earlier specification",
                    "earlier_work_identifier": "doi:10.0000/earlier", "what_changed": "fixes a flaw",
                    "words_that_show_it": "A table has rows and columns", "limits": f"{TAG} limits"}],
                    "origin_of_its_own_subject": "names_an_earlier_origin", "note": ""})
        return {"pages": out}
    if stage == "identity":
        pages = block("pages") or []
        unknown = variant.get("identity_unknown") or []
        out = []
        for x in pages:
            k = x.get("key")
            if k in unknown or variant.get("identity_all_unknown"):
                out.append({"key": k, "authors": [], "published": "", "version_or_edition": "", "identifier": "",
                            "role": "secondary_aid", "title_as_published": "", "words_that_show_it": "",
                            "unknown": ["authors", "published", "version_or_edition", "identifier"], "note": f"{TAG} the page does not say"})
            else:
                out.append({"key": k, "authors": [f"{TAG} Author"], "published": "2024-02-03", "version_or_edition": "1.2",
                            "identifier": "doi:10.0000/fake", "role": variant.get("identity_role") or "official_documentation",
                            "title_as_published": f"{TAG} real title", "words_that_show_it": "A table has rows and columns",
                            "unknown": [], "note": ""})
        return {"pages": out}
    if stage == "attribution_review":
        srcs = block("sources") or []
        no = variant.get("attr_no") or []
        # Per-relationship judgements, off unless a test asks for them, so every existing expectation is unchanged.
        # `attr_rel` is the answer this reviewer gives for each claimed relationship; `attr_rel_flip` overrides it
        # for named sources, which is how a test makes ONE relationship change its answer between two runs while
        # the source's overall verdict stays exactly where it was.
        rel = variant.get("attr_rel")
        flip = variant.get("attr_rel_flip") or {}

        def rels_for(x):
            if not rel:
                return {}
            got = flip.get(x["id"], rel)
            return {"relationships": [{"earlier_work": r.get("earlier_work"), "relation": r.get("relation"),
                                       "supported": got, "reason": f"{TAG} per-relationship reason"}
                                      for r in (x.get("lineage_given") or [])]}

        return {"verdict": "concerns", "summary": f"{TAG} attribution", "sources": [dict({"id": x["id"], "identity_correct": "no" if x["id"] in no else "yes", "role_correct": "yes", "lineage_supported": "none_claimed", "reason": f"{TAG} reason"}, **rels_for(x)) for x in srcs], "origin_unknown": [], "disputed_or_branching": [], "current_relevance_concerns": []}
    if stage == "outline_review":
        must = [{"severity": "must_fix", "area": "time", "finding": f"{TAG} time is tight", "suggestion": "trim"}] if variant.get("ol") == "must" else []
        return {"verdict": "concerns" if must else "sound", "summary": f"{TAG} feasibility", "findings": must, "project_checks": [{"project": "P1", "feasible": "yes", "why": "ok"}], "time_verdict": {"fits": not must, "why": "ok"}}
    if stage == "materials" and "<topics_this_session_teaches_and_practises>" in prompt:
        k, minutes = int(attr("session")), int(attr("minutes"))
        this = block("this_session") or {}
        tp = block("topics_this_session_teaches_and_practises") or []
        m_ = re.search(r"learners have (\d+) minutes of independent work", prompt)
        ind = int(m_.group(1)) if m_ else 0
        out = session(this.get("title") or f"{TAG} session {k}", minutes, this.get("topics") or topics, number=k)
        out["activities"][2]["worked_example"] = f"{TAG} a worked example"
        out["activities"][2]["misconceptions"] = [{"belief": "a column is a row", "response": "show one"}]
        out["teaches_nodes"] = [n["id"] for n in tp if n.get("teaches_here")]
        out["independent_work"] = {"minutes": ind, "tasks": [{"title": "Alone", "minutes": ind, "instructions": ["Do a.", "Do b."], "handout": "sheet", "self_check": ["Check"], "deliverable": "a file, sent to the shared folder"}] if ind else []}
        proj = block("projects_this_session_carries") or []
        out["project_work"] = [{"project": p_["id"], "milestone": "m", "what_learners_do": "work"} for p_ in proj]
        out["assets"] = []
        if k == 1:
            out["assets"] = [{"name": "data.csv", "kind": "dataset", "language": "", "purpose": f"{TAG} synthetic practice data, not real measurements", "provenance": "synthetic_practice", "source_id": "", "run": "no_run", "expected_output": "", "content": "a,b\n1,2\n3,4\n5,6\n"},
                             {"name": "count.py", "kind": "code", "language": "python", "purpose": "count rows", "provenance": "authored", "source_id": "", "run": "run", "expected_output": "rows 3", "content": variant.get("code") or CODE_OK}]
        return out
    if stage == "project":
        pr = block("approved_project_in_the_outline") or {}
        mn = pr.get("minutes") or {}
        tot = mn.get("live", 0) + mn.get("independent", 0)
        av = pr.get("available_after_session", 1)
        return {"title": pr.get("title"), "kind": pr.get("kind"), "purpose": f"{TAG} purpose", "learner_brief": f"{TAG} the whole brief", "prerequisites": [{"node": n, "name": n, "taught_in_session": 1} for n in pr.get("nodes_required") or []],
                "inputs": [], "milestones": [{"when": "week 1", "session": av, "what": "first", "minutes": tot - 10, "check": "look"}, {"when": "week 2", "session": av, "what": "second", "minutes": 10, "check": "look"}],
                "deliverables": ["a file"], "time": {"live": mn.get("live", 0), "independent": mn.get("independent", 0)},
                "rubric": [{"criterion": c, "levels": [{"level": l, "descriptor": f"{TAG} {l}"} for l in ("low", "mid", "high")]} for c in ("accuracy", "limits", "clarity")],
                "example_or_solution_guidance": f"{TAG} guidance", "solution_assets": [], "feedback_route": "a peer, by Friday", "revision_route": "revise and resend", "teacher_guidance": ["watch"],
                "common_errors": [{"belief": "b", "response": "r"}], "claims": [], "assumptions": []}
    if stage == "review" and "<topic_map_approved>" in prompt:
        areas = ("sources", "feasibility", "topic_connections", "assessment_alignment", "timing", "clarity", "continuity", "constraints", "foundations", "projects")
        return {"areas": [{"area": a, "verdict": "concerns", "summary": f"{TAG} {a}"} for a in areas], "findings": [{"severity": "should_fix", "area": "projects", "session": 0, "project": "P1", "finding": f"{TAG} finding", "suggestion": f"{TAG} suggestion"}],
                "teacher_could_run_it": {"answer": "with_changes", "why": f"{TAG} why"}}
    return None


out = v2_out()
if out is not None:
    pass
elif stage == "research":
    url = "https://example.org/test-double-source"
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": f"{topics[0]} teaching"}}]}})
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "WebFetch", "input": {"url": url, "prompt": "read"}}]}})
    # "fetch" in the plan rehearses what can happen to a request for a page: ok, error, redirect, short, none (no result at all).
    how = plan.get("fetch", "ok")
    body = {"ok": "The page says that beginners scan a page before they read it, and gives three examples of this in practice.", "error": "Request failed with status code 403",
            "redirect": "REDIRECT DETECTED: The URL redirects to a different host. Make a new request with the redirect URL.", "short": "ok"}.get(how)
    if body is not None:
        emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": how == "error", "content": [{"type": "text", "text": body}]}]}})
    for extra in plan.get("extra_results") or []:
        emit({"type": "user", "message": {"content": [extra]}})
    out = {"sources": [{"title": f"{TAG} opened source", "url": url, "publisher": "Example", "year": "2020", "kind": "textbook_or_reference", "topic": topics[0], "claim": f"{TAG} claim one", "finding": "A finding.", "quote": "", "strength": "direct", "limits": "None stated."},
                       {"title": f"{TAG} source never opened", "url": "https://example.org/not-opened", "publisher": "Example", "year": "2021", "kind": "other", "topic": "teaching approach", "claim": f"{TAG} claim two", "finding": "A finding.", "quote": "", "strength": "direct", "limits": ""}],
           "not_opened": [{"title": "Seen only in results", "url": "https://example.org/unread", "why_relevant": "Looked relevant."}], "open_questions": [f"{TAG} an open question"], "combination_evidence": {"status": "weak" if len(topics) > 1 else "not_applicable", "note": f"{TAG} note"}}
elif stage == "ideas":
    url = "https://example.org/test-double-dated-page"
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": "topics people are learning"}}]}})
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "WebFetch", "input": {"url": url, "prompt": "read"}}]}})
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "Published 3 March 2026. Enrolment in short courses on the subject doubled this year."}]}]}})
    out = {"searched_on": "2026-09-29",
           "ideas": [{"idea": f"{TAG} idea with a dated page", "why_now": "A page dated 3 March 2026 reports enrolment doubling this year.", "suits": "Adults new to it", "make": "A one-page plan", "combines_with": "Writing", "uncertainty": "One page, one country.",
                      "evidence": [{"title": "Dated page", "url": url, "publisher": "Example", "dated": "3 March 2026", "what_it_says": "Enrolment doubled this year."}]},
                     {"idea": f"{TAG} idea whose page never arrived", "why_now": "Said to be popular.", "suits": "Anyone", "make": "A poster", "combines_with": "", "uncertainty": "Unknown.",
                      "evidence": [{"title": "Never opened", "url": "https://example.org/never-opened", "publisher": "Example", "dated": "2026", "what_it_says": "Claims popularity."}]},
                     {"idea": f"{TAG} idea with an undated page", "why_now": "Said to be rising.", "suits": "Anyone", "make": "A list", "combines_with": "", "uncertainty": "No date.",
                      "evidence": [{"title": "Undated", "url": url, "publisher": "Example", "dated": "", "what_it_says": "Rising."}]}],
           "shortfall": f"{TAG} only one idea had a dated page that opened.", "not_opened": [{"title": "Seen in results", "url": "https://example.org/unread"}]}
elif stage == "outline":
    n_s = int(attr("sessions", "3"))
    mode_ = brief.get("mode")
    fb = block("team_feedback")
    sessions = []
    for i in range(n_s):
        st = [topics[i % len(topics)]] if mode_ == "separate" or (mode_ == "linked" and i < n_s - 1) else list(topics)
        sessions.append({"title": f"{TAG} session {i + 1}" + (" (revised)" if fb else ""), "outcome": f"{TAG} learners can do part {i + 1}", "serves": "It is a step to the outcome.", "topics": st,
                         "contributions": [{"topic": t, "gives": f"{TAG} {t} gives a method"} for t in st], "builds_on": [i] if i else [], "key_task": f"{TAG} learners are given X and hand in Y", "evidence_of_learning": f"{TAG} a finished Y"})
    out = {"course_outcome": brief.get("outcome", ""), "final_evidence": f"{TAG} a finished piece of work", "feasibility": {"fits": True, "concern": ""}, "sessions": sessions,
           "integration": {"status": "kept_separate" if mode_ == "separate" else "single_topic" if len(topics) < 2 else "partly", "reason": f"{TAG} reason", "joining_task": ""}, "assumptions": [f"{TAG} assumption"]}
elif stage == "materials":
    k, minutes = int(attr("session")), int(attr("minutes"))
    this = block("this_session") or {}
    wrong = k in (plan.get("bad_minutes_on") or []) and ("DID NOT PASS" not in prompt or plan.get("bad_minutes_always"))
    out = session(this.get("title") or f"{TAG} session {k}", minutes, this.get("topics") or topics, wrong, number=k)
elif stage == "review":
    out = {"areas": [{"area": a, "verdict": "concerns", "summary": f"{TAG} summary for {a}"} for a in ("sources", "feasibility", "topic_connections", "assessment_alignment", "timing", "clarity", "continuity", "constraints")],
           "findings": [{"severity": "should_fix", "area": "clarity", "session": 1, "finding": f"{TAG} finding", "suggestion": f"{TAG} suggestion"}], "teacher_could_run_it": {"answer": "with_changes", "why": f"{TAG} why"}}
elif stage == "edit":
    scope, minutes = attr("scope"), int(attr("minutes"))
    req = str(block("team_request") or "")
    if "unclear" in req.lower():
        cur = block("activity_to_change") if scope == "activity" else block("session")
        out = {"acted": False, "note": f"{TAG} the request was unclear.", ("activity" if scope == "activity" else "session"): session("x", minutes, topics)["activities"][1] if scope == "activity" else session("x", minutes, topics)}
    elif scope == "activity":
        a = block("activity_to_change") or activity("try", "x", 10)
        a = {k: a.get(k, [] if k in ("instructions", "materials", "teacher", "misconceptions", "success") else "") for k in ("kind", "title", "goal", "minutes", "instructions", "materials", "handout", "worked_example", "teacher", "misconceptions", "success")}
        a["goal"] = f"{TAG} changed on request: {req[:60]}"
        out = {"acted": True, "note": f"{TAG} changed the goal.", "activity": a}
    else:
        cur = block("session") or {}
        s_ = session(cur.get("title") or "x", minutes, [c.get("topic") for c in cur.get("contributions") or []] or topics)
        s_["outcome"] = f"{TAG} changed on request: {req[:60]}"
        out = {"acted": True, "note": f"{TAG} changed the outcome.", "session": s_}
else:
    out = {}

emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "StructuredOutput", "input": out}]}})
emit({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(out), "structured_output": out, "num_turns": 2, "usage": {"input_tokens": 10, "output_tokens": 20}, "modelUsage": {"test-double": {"outputTokens": 20}}})
