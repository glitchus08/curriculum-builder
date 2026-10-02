"""Checks for the expanded curriculum pipeline: the topic map, per-topic research, separate reviewers, projects, independent time and running supplied code.

The end-to-end cases use the test double in place of Claude. They rehearse the pipeline's own rules and prove nothing about the quality of real answers.
Run: python3 -m unittest discover -s tests/server -t .
"""
import copy
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

TMP = os.environ.setdefault("LOOM_DATA_DIR", tempfile.mkdtemp(prefix="loom-test-"))
HERE = Path(__file__).resolve().parent.parent
os.environ["LOOM_CLAUDE_BIN"] = str(HERE / "fake_claude.py")
os.environ["LOOM_SKIP_LINK_CHECK"] = "1"

from loom_server import engine, pipeline, storage  # noqa: E402

BRIEF = {"format": "Course", "topics": ["Python", "Charts"], "mode": "shared", "audience": "Adults", "prior": "New", "priorKey": "new", "outcome": "Make an honest chart", "delivery": "Blended", "deliveryKey": "blended", "requirements": []}
PLAN = {"sessions": 4, "minutes": [60, 60, 60, 60], "unit": "Meeting", "total": 240, "weekly": True, "weeks": 2, "meetingsPerWeek": 2, "independent": {"perWeekMinutes": 60, "weeks": 2, "totalMinutes": 120}}


def node(i, name, kind="foundation", role="required", needed=None, req=None, est=30, **kw):
    return dict({"id": i, "name": name, "kind": kind, "role": role, "why_needed": "because", "needed_by": needed if needed is not None else ["OUTCOME"], "requires": req or [], "depth": "working", "entry_reached": True, "below_entry": "", "est_minutes": est, "needs_evidence": True, "research_questions": []}, **kw)


def good_map():
    return {"nodes": [node("N1", "Python", "requested", req=["N3"]), node("N2", "Charts", "requested", req=["N3"]), node("N3", "Reading a table", needed=["N1", "N2"], req=["N4"]), node("N4", "Files", role="already_known", needed=["N3"])],
            "outcome_needs": [], "assumed_entry": [], "stop_reason": "", "unresolved": []}


class MapRules(unittest.TestCase):
    def test_a_sound_map_passes_and_is_ordered_with_foundations_first(self):
        m = good_map()
        self.assertEqual(pipeline.check_map(m, BRIEF), [])
        d = pipeline.derive_map(m)
        order = d["derived"]["order"]
        self.assertLess(order.index("N4"), order.index("N3"))
        self.assertLess(order.index("N3"), order.index("N1"))
        self.assertEqual(d["derived"]["requiredMinutes"], 30 + 30 + 30)

    def test_a_circle_is_found_and_named(self):
        m = good_map()
        m["nodes"][3]["requires"] = ["N3"]
        p = pipeline.check_map(m, BRIEF)
        self.assertTrue(any("circle" in x for x in p), p)

    def test_an_addition_that_nothing_needs_is_refused_as_unrelated(self):
        m = good_map()
        m["nodes"].append(node("N5", "Trivia", "subtopic", needed=[]))
        self.assertTrue(any("nothing that is requested needs it" in x for x in pipeline.check_map(m, BRIEF)))

    def test_a_chain_of_additions_is_justified_through_what_needs_it(self):
        m = good_map()
        m["nodes"].append(node("N5", "Number formats", needed=["N3"]))
        self.assertEqual(pipeline.check_map(m, BRIEF), [])

    def test_every_requested_topic_must_be_present_and_named_as_asked(self):
        m = good_map()
        m["nodes"][1]["name"] = "Graphs"
        self.assertTrue(any("“Charts” is not in the map" in x for x in pipeline.check_map(m, BRIEF)))

    def test_one_shared_foundation_is_one_node(self):
        m = good_map()
        m["nodes"].append(node("N5", "reading  a TABLE", needed=["N1"]))
        self.assertTrue(any("appears twice" in x for x in pipeline.check_map(m, BRIEF)))

    def test_a_missing_foundation_below_the_entry_level_is_an_open_gap_not_a_silent_one(self):
        m = good_map()
        m["nodes"].append(node("N5", "Number formats", needed=["N3"], entry_reached=False, below_entry="how numbers are stored"))
        self.assertEqual(pipeline.check_map(m, BRIEF), [])
        self.assertIn("how numbers are stored", pipeline.derive_map(m)["derived"]["openGaps"][0])

    def test_a_topic_whose_prerequisites_are_in_the_map_is_not_a_gap_however_the_author_marked_it(self):
        m = good_map()
        m["nodes"][2].update(entry_reached=False, below_entry="needs files first")  # N3 requires N4, which is in the map
        d = pipeline.derive_map(dict(m, unresolved=["The dataset is not chosen."]))["derived"]
        self.assertEqual(d["openGaps"], [])
        self.assertEqual(d["unresolved"], ["The dataset is not chosen."], "what the author left unresolved is kept, apart from gaps")

    def test_a_reviewer_addition_is_merged_once_and_puts_the_new_topic_before_what_needs_it(self):
        grown, names = pipeline.add_nodes(good_map(), [{"name": "Counting rows", "why_needed": "x", "needed_by": ["N1"], "requires": [], "est_minutes": 15}, {"name": "counting  ROWS"}, {"name": "Reading a table"}], "review")
        self.assertEqual(names, ["Counting rows"])
        self.assertEqual(pipeline.check_map(grown, BRIEF), [])
        d = pipeline.derive_map(grown)["derived"]["order"]
        new = [n["id"] for n in grown["nodes"] if n["name"] == "Counting rows"][0]
        self.assertLess(d.index(new), d.index("N1"))


class Sizes(unittest.TestCase):
    def test_project_expectations_follow_the_whole_time_and_short_formats_are_not_forced(self):
        self.assertEqual(pipeline.project_policy({"total": 10})["major"], 0)
        self.assertEqual(pipeline.project_policy({"total": 120}), dict(pipeline.project_policy({"total": 120}), minor=1, major=0))
        self.assertEqual((pipeline.project_policy({"total": 1080, "independent": {"totalMinutes": 720}})["minor"], pipeline.project_policy({"total": 1080, "independent": {"totalMinutes": 720}})["major"]), (2, 1))

    def test_live_and_independent_time_are_each_counted_once(self):
        a = pipeline.accounting({"total": 1080, "minutes": [90] * 12, "independent": {"totalMinutes": 720}})
        self.assertEqual((a["liveMinutes"], a["independentMinutes"], a["combinedMinutes"]), (1080, 720, 1800))
        self.assertIn("18 h live + 12 h independent = 30 h", a["statement"])


def good_outline(n=4):
    return {"sessions": [{"title": f"s{i}", "teaches": [["N3"], ["N1"], ["N2"], []][i] if i < 4 else [], "practises": [], "independent_work": {"minutes": 30, "tasks": ["t"]}} for i in range(n)],
            "projects": [{"id": "P1", "kind": "minor", "title": "a", "nodes_required": ["N3"], "available_after_session": 2, "hosted_in_sessions": [3], "milestones": [{"session": 3, "what": "x", "live_minutes": 20, "independent_minutes": 20}], "deliverable": "d", "minutes": {"live": 20, "independent": 20}},
                         {"id": "P2", "kind": "major", "title": "b", "nodes_required": ["N1", "N2"], "available_after_session": 3, "hosted_in_sessions": [4], "milestones": [{"session": 4, "what": "x", "live_minutes": 30, "independent_minutes": 40}], "deliverable": "d", "minutes": {"live": 30, "independent": 40}}],
            "deferred": [], "time_conflict": {"exists": False, "explanation": "", "options": []}}


class OutlineRules(unittest.TestCase):
    def check(self, o, plan=PLAN):
        return pipeline.check_outline_v2(o, pipeline.derive_map(good_map()), BRIEF, plan)

    def test_a_sound_outline_passes(self):
        self.assertEqual(self.check(good_outline()), [])

    def test_a_dependent_topic_taught_before_its_foundation_is_refused(self):
        o = good_outline()
        o["sessions"][0]["teaches"], o["sessions"][1]["teaches"] = ["N1"], ["N3"]
        self.assertTrue(any("before what it needs" in x for x in self.check(o)))

    def test_a_required_foundation_is_never_dropped_quietly(self):
        o = good_outline()
        o["sessions"][0]["teaches"] = []
        self.assertTrue(any("Never drop a foundation quietly" in x for x in self.check(o)))

    def test_it_may_be_deferred_only_by_declaring_a_time_conflict_with_options(self):
        o = good_outline()
        o["sessions"][0]["teaches"] = []
        o["deferred"] = [{"node": "N3", "reason": "no time"}]
        self.assertTrue(self.check(o))
        o["time_conflict"] = {"exists": True, "explanation": "x", "options": [{"label": "a", "effect": ""}, {"label": "b", "effect": ""}]}
        self.assertEqual([x for x in self.check(o) if "Never drop" in x], [])

    def test_no_project_may_depend_on_something_taught_after_it_opens(self):
        o = good_outline()
        o["projects"][0]["nodes_required"] = ["N2"]
        self.assertTrue(any("taught in session 3, after the project becomes available in session 2" in x for x in self.check(o)))

    def test_a_course_of_this_size_needs_its_projects(self):
        o = good_outline()
        o["projects"] = []
        p = self.check(o)
        self.assertTrue(any("minor project" in x for x in p) and any("major project" in x for x in p), p)

    def test_independent_minutes_must_add_up_each_week(self):
        o = good_outline()
        o["sessions"][1]["independent_work"]["minutes"] = 20
        self.assertTrue(any("Week 1's independent work adds up to 50" in x for x in self.check(o)))

    def test_an_overcommitted_map_must_say_so(self):
        m = good_map()
        for n in m["nodes"]:
            if n["role"] == "required":
                n["est_minutes"] = 200
        p = pipeline.check_outline_v2(good_outline(), pipeline.derive_map(m), BRIEF, PLAN)
        self.assertTrue(any("time_conflict" in x for x in p), p)

    def test_the_project_time_and_mislabelled_coverage(self):
        o = good_outline()
        cov = pipeline.coverage(o, pipeline.derive_map(good_map()))
        self.assertEqual([r["taughtInSession"] for r in cov["rows"] if r["node"] == "N3"], [1])
        self.assertEqual(cov["requiredNotTaught"], [])


class Evidence(unittest.TestCase):
    def test_a_quote_must_be_in_what_the_fetch_returned(self):
        self.assertTrue(pipeline.quote_found("Each row is one record", "A table: each row is one record, and more."))
        self.assertFalse(pipeline.quote_found("words never said anywhere at all", "A table has rows."))
        self.assertIsNone(pipeline.quote_found("", "x"))

    def test_the_same_page_and_claim_found_for_two_topics_is_one_source_but_a_different_claim_is_its_own(self):
        a = {"sources": [{"url": "https://e.org/a/", "claim": "The claim", "node_ids": ["N1"], "fetch": "failed"}], "searches": [], "pagesOpened": [], "pagesAskedFor": []}
        b = {"sources": [{"url": "https://E.org/a", "claim": "the  claim", "node_ids": ["N2"], "fetch": "retrieved"}, {"url": "https://e.org/a", "claim": "Another claim", "node_ids": ["N2"], "fetch": "retrieved"}, {"url": "https://e.org/b", "claim": "c3", "node_ids": ["N2"]}], "searches": [], "pagesOpened": [], "pagesAskedFor": []}
        m = pipeline.merge_research([a, b])
        self.assertEqual([s["id"] for s in m["sources"]], ["S1", "S2", "S3"])
        self.assertEqual(m["sources"][0]["node_ids"], ["N1", "N2"])
        self.assertEqual(m["sources"][0]["fetch"], "retrieved", "a later sighting that arrived replaces an earlier one that did not")
        self.assertEqual(m["sources"][1]["claim"], "Another claim", "a second claim on one page keeps its own strength and quote check")

    def test_a_reviewer_can_only_lower_a_source(self):
        s = {"strength": "direct", "limits": ""}
        self.assertEqual(pipeline.source_effect(s, "yes")["strength"], "direct")
        self.assertEqual(pipeline.source_effect(s, "partly")["strength"], "partial")
        self.assertEqual(pipeline.source_effect(s, "no")["strength"], "background")
        self.assertEqual(pipeline.source_effect({"strength": "background", "limits": ""}, "partly")["strength"], "background")

    def test_batches_are_in_teaching_order_and_the_cap_names_what_it_left(self):
        m = good_map()
        b, left = pipeline.plan_batches(m)
        self.assertEqual(b[0]["key"], "approach")
        self.assertEqual([n for x in b[1:] for n in x["nodes"]], ["N3", "N1", "N2"])
        self.assertEqual(left, [])
        big = {"nodes": [node("N1", "Python", "requested")] + [node(f"M{i}", f"Sub {i}", "subtopic", needed=["N1"]) for i in range(22)]}
        b, left = pipeline.plan_batches(big)
        self.assertEqual(len(left), 23 - pipeline.MAX_RESEARCH_NODES)


class DatasetOrigin(unittest.TestCase):
    ASSET = {"name": "air.csv", "kind": "dataset", "provenance": "public_source", "source_id": "S2", "content": "site,pm25\nA,12.4\nB,18.9\nC,7.35\nD,22.1\nE,15.6\n"}

    def test_values_that_are_in_the_page_pass_and_invented_ones_fail(self):
        r = pipeline.origin_checks([self.ASSET], {"S2": "Readings: A 12.4, B 18.9, C 7.35, D 22.1 micrograms."})
        self.assertEqual(r[0]["level"], "origin_unverified", "numbers that appear in a page are never provenance")
        self.assertIn("NOT verified as original data", r[0]["reason"])
        r = pipeline.origin_checks([self.ASSET], {"S2": "A page about air quality that lists no readings at all."})
        self.assertEqual(r[0]["level"], "origin_failed")
        self.assertTrue(pipeline.asset_problems(r, "Assets"))

    def test_a_source_that_never_arrived_cannot_be_the_origin_and_a_practice_dataset_is_not_checked(self):
        self.assertEqual(pipeline.origin_checks([self.ASSET], {})[0]["level"], "origin_failed")
        self.assertEqual(pipeline.origin_checks([dict(self.ASSET, provenance="synthetic_practice")], {}), [])
        self.assertEqual(pipeline.origin_checks([dict(self.ASSET, content="a,b\n1,2\n")], {"S2": "x"})[0]["level"], "origin_unverified")


@unittest.skipUnless(pipeline.sandbox_available(), "no sandbox on this computer")
class RunningCode(unittest.TestCase):
    def test_code_runs_on_the_supplied_files(self):
        r = pipeline.run_python("import csv\nprint(len(list(csv.DictReader(open('d.csv')))))\n", {"d.csv": "a\n1\n2\n"})
        self.assertEqual((r["state"], r["output"].strip()), ("ran", "2"))

    def test_code_cannot_write_outside_its_own_folder_or_use_the_network(self):
        r = pipeline.run_python(f"open('{TMP}/escape.txt','w').write('x')\n", {})
        self.assertEqual(r["state"], "failed")
        self.assertFalse((Path(TMP) / "escape.txt").exists())
        r = pipeline.run_python("import socket\nsocket.create_connection(('93.184.216.34',80),timeout=2)\n", {})
        self.assertEqual(r["state"], "failed")

    def test_a_missing_library_is_reported_as_not_run_and_never_as_a_pass_or_a_failure(self):
        r = pipeline.run_python("import a_library_nobody_has\n", {})
        self.assertEqual(r["state"], "not_run")

    def test_a_starter_with_gaps_is_only_parsed_and_broken_code_fails(self):
        res = pipeline.run_assets([{"name": "s.py", "kind": "starter", "run": "no_run", "content": "x = = 1\n"}], [])
        self.assertEqual(res[0]["level"], "failed")  # even a starter must parse
        res = pipeline.run_assets([{"name": "s.py", "kind": "starter", "run": "no_run", "content": "x = None  # fill in\n"}], [])
        self.assertEqual(res[0]["level"], "syntax_only")
        res = pipeline.run_assets([{"name": "a.py", "kind": "solution", "run": "run", "content": "raise SystemExit(2)\n"}], [])
        self.assertEqual(res[0]["level"], "failed")


# ---------------------------------------------------------------- the whole pipeline with the test double

def plan_file(name, **kw):
    f = Path(TMP) / f"plan-{name}.json"
    f.write_text(json.dumps({"calls": 0, **kw}))
    os.environ["FAKE_CLAUDE_PLAN"] = str(f)
    return f


def new_course(name):
    return storage.create_course("pipe", json.dumps({"v": 1}), name)["id"]


def wait(cid, want=("paused", "waiting_approval", "done"), limit=60):
    end = time.time() + limit
    while time.time() < end:
        rec = engine.runner("pipe", cid).load()
        if rec and rec["status"] in want and not engine.runner("pipe", cid).busy():
            return engine.read("pipe", cid)
        time.sleep(0.1)
    raise AssertionError("did not settle: " + json.dumps(engine.runner("pipe", cid).load())[:500])


def go(cid, action, **payload):
    engine.runner("pipe", cid).start(action, {"action": action, **payload})
    return wait(cid)


def begin(name, **variant):
    f = plan_file(name, variant=variant)
    cid = new_course(name)
    return f, cid, go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d", pipeline=2)


def prompts_roles():
    from loom_server import evidence
    return evidence.ROLES


def log(f):
    return json.loads(f.read_text())["log"]


class WholePipeline(unittest.TestCase):
    def test_the_steps_run_in_order_as_separate_requests_and_only_research_reads_the_web(self):
        f, cid, rec = begin("order")
        self.assertEqual(rec["status"], "waiting_approval")
        stages = [(c["stage"]) for c in log(f)]
        self.assertEqual(stages, ["map", "foundation_review", "research", "research", "source_review", "attribution_review", "outline", "outline_review"],
                         "Loom's own retrieval needs no model; the attribution check is a model request and is part of the ordinary route")
        tools = {c["stage"]: c["tools"] for c in log(f)}
        self.assertEqual(tools["research"], "WebSearch,WebFetch")
        self.assertTrue(all(c["tools"] == "" for c in log(f) if c["stage"] != "research"))
        self.assertEqual(rec["pipeline"], 2)
        self.assertEqual(rec["accounting"]["combinedMinutes"], 360)
        for k in ("map", "foundation_review", "source_review", "outline_review"):
            self.assertEqual(rec["stages"][k]["status"], "done", k)

    def test_research_covers_the_foundations_and_the_requested_topics_and_says_what_each_topic_has(self):
        f, cid, rec = begin("cover")
        out = rec["stages"]["research"]["output"]
        self.assertEqual([b["key"] for b in rec["stages"]["research"]["batches"]], ["approach", "nodes-1"])
        cov = {c["node"]: c for c in out["nodeCoverage"]}
        self.assertEqual(set(cov), {"N1", "N2", "N3"})
        self.assertTrue(all(c["sources"] for c in cov.values()), cov)
        # what a page really returned is kept with its source, and the quote was found in it
        s = out["sources"][1]
        self.assertIn("each row is one record", s["retrievedExcerpt"].lower())
        self.assertTrue(s["quoteFound"])

    def test_a_quote_that_the_page_never_said_is_dropped_and_the_source_lowered(self):
        f, cid, rec = begin("badquote", quote="bad")
        s = rec["stages"]["research"]["output"]["sources"][1]
        self.assertFalse(s["quoteFound"] is True)
        self.assertEqual(s["quote"], "")
        self.assertEqual(s["strength"], "partial")
        self.assertIn("not found in what the fetch returned", s["limits"])

    def test_the_source_reviewer_can_lower_a_source_and_its_judgement_is_kept_with_it(self):
        f, cid, rec = begin("srno", sr_no=["S2"])
        src = {s["id"]: s for s in rec["stages"]["research"]["output"]["sources"]}
        self.assertEqual(src["S2"]["strength"], "background")
        self.assertEqual(src["S2"]["sourceReview"]["supports_claim"], "no")
        self.assertEqual(src["S1"]["strength"], "direct")
        rnd = rec["stages"]["source_review"]["rounds"][0]
        self.assertTrue(rnd["inputFingerprint"] and rnd["requestId"])

    def test_targeted_research_is_bounded_to_one_round_and_the_reviewer_is_not_asked_twice_for_more(self):
        f, cid, rec = begin("targeted", sr="targeted")
        self.assertEqual([c["stage"] for c in log(f)].count("source_review"), 2)
        self.assertEqual([c["stage"] for c in log(f)].count("research"), 3)
        rounds = rec["stages"]["source_review"]["rounds"]
        self.assertEqual(len(rounds), 2)
        self.assertTrue(rounds[1]["finalRound"])
        self.assertEqual(rounds[1]["targetedAsked"], [])

    def test_a_targeted_search_stopped_half_way_is_finished_on_resume_before_the_audit_goes_on(self):
        # calls: 1 map, 2 foundations, 3 approach, 4 nodes, 5 audit round 1 (asks), 6 targeted search (stopped by a limit)
        f = plan_file("resume-targeted", variant={"sr": "targeted"}, fail={"6": "limit"})
        cid = new_course("resume-targeted")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d", pipeline=2)
        self.assertEqual(rec["status"], "paused")
        self.assertEqual([b["status"] for b in rec["stages"]["research"]["batches"]], ["done", "done", "todo"])
        rec = go(cid, "resume")
        self.assertEqual(rec["status"], "waiting_approval")
        self.assertEqual([b["status"] for b in rec["stages"]["research"]["batches"]], ["done", "done", "done"])
        rounds = rec["stages"]["source_review"]["rounds"]
        self.assertEqual(len(rounds), 2)
        self.assertTrue(rounds[1]["finalRound"])
        self.assertIn("targeted-1", [b["key"] for b in rec["stages"]["research"]["batches"]])

    def test_a_stop_during_the_automatic_revision_does_not_lose_what_the_reviewer_asked_for(self):
        # calls: 1 map, 2 foundations, 3 approach, 4 nodes, 5 audit, 6 attribution, 7 outline, 8 delivery review (must fix), 9 revised outline (stopped)
        f = plan_file("resume-revise", variant={"ol": "must"}, fail={"9": "limit"}, watch=["time is tight"])
        cid = new_course("resume-revise")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d", pipeline=2)
        self.assertEqual(rec["status"], "paused")
        rec = go(cid, "resume")
        self.assertEqual(rec["status"], "waiting_approval")
        outlines = [c for c in log(f) if c["stage"] == "outline"]
        self.assertEqual([bool(c["marks"]) for c in outlines], [False, True, True], "the retry carries the reviewer's finding, not a blank request")

    def test_a_format_too_short_for_a_project_finishes_and_is_reviewed_and_is_not_left_waiting(self):
        short = {"sessions": 2, "minutes": [20, 20], "unit": "Block", "total": 40, "weekly": False}
        self.assertEqual(pipeline.project_policy(short)["major"], 0)
        f = plan_file("short", variant={"noprojects": True, "conflict": True})  # 130 minutes of required topics in 40: the conflict must be declared
        cid = new_course("short")
        rec = go(cid, "begin", brief=BRIEF, plan=short, digest="d", pipeline=2)
        self.assertEqual(rec["status"], "waiting_approval")
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])
        self.assertEqual((rec["status"], rec["stages"]["projects"]["status"], rec["stages"]["review"]["status"]), ("done", "done", "done"))
        self.assertEqual([c["stage"] for c in log(f)].count("project"), 0)

    def test_a_source_the_audit_lowered_no_longer_counts_as_support_for_its_topic_and_a_later_yes_does_not_raise_it(self):
        f, cid, rec = begin("cov-lowered", sr_no=["S2"])
        cov = {c["node"]: c for c in rec["stages"]["research"]["output"]["nodeCoverage"]}
        self.assertEqual(cov["N3"]["status"], "none_found", "S2 was its only source and the audit found it does not support the claim")
        self.assertEqual(cov["N3"]["sources"], ["S2"])
        # the reviewer can only lower: a later round that says yes leaves the lower verdict standing
        rs = rec["stages"]["research"]
        self.assertEqual(engine.pipeline.source_effect({"strength": "background", "limits": ""}, "yes")["strength"], "background")

    def test_the_material_a_review_was_asked_to_judge_survives_a_poll_and_includes_the_projects(self):
        f, cid, rec = begin("review-material")
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])
        sessions = [dict(u["output"], number=i + 1, minutes=60) for i, u in enumerate(rec["stages"]["materials"]["sessions"])]
        projects = [dict(u["output"], id=u["outline"]["id"]) for u in rec["stages"]["projects"]["units"]]
        engine.runner("pipe", cid).start("review", {"action": "review", "sessions": sessions, "projects": projects})
        rec = wait(cid)
        self.assertEqual(rec["stages"]["review"]["inputFingerprint"], engine.content_print({"sessions": sessions, "projects": projects}), "the page fingerprints sessions and projects together")
        engine.read("pipe", cid)  # a poll must not strip what is on disk
        self.assertIsNotNone(engine.runner("pipe", cid).load()["stages"]["review"]["input"])

    def test_a_circle_in_the_map_is_sent_back_once_and_the_repair_is_recorded(self):
        f, cid, rec = begin("cycle", map="cycle")
        rep = [c for c in log(f) if c["stage"] == "map"]
        self.assertEqual(len(rep), 2)
        self.assertTrue(rep[1]["repair"])
        self.assertTrue(any("circle" in p for p in rec["calls"][0]["problems"]))

    def test_a_reviewer_who_finds_a_missing_foundation_gets_it_added_and_it_is_named_as_theirs(self):
        f, cid, rec = begin("missing", fr="missing")
        added = [n for n in rec["stages"]["map"]["output"]["nodes"] if n.get("addedBy")]
        self.assertEqual([n["name"] for n in added], ["Counting rows"])
        self.assertEqual(rec["stages"]["foundation_review"]["addedNodes"], ["Counting rows"])
        new = added[0]["id"]
        self.assertIn(new, [i for b in rec["stages"]["research"]["batches"] for i in b["nodes"]])  # it was researched too

    def test_an_outline_that_teaches_a_topic_before_its_foundation_is_sent_back(self):
        f, cid, rec = begin("order-bad", outline="order")
        outs = [c for c in log(f) if c["stage"] == "outline"]
        self.assertEqual(len(outs), 2)
        self.assertTrue(any("before what it needs" in p for p in rec["calls"][[c["stage"] for c in rec["calls"]].index("outline")]["problems"]))

    def test_a_must_fix_from_the_feasibility_reviewer_sends_the_outline_back_once_then_shows_what_is_left(self):
        f, cid, rec = begin("must", ol="must")
        self.assertEqual([c["stage"] for c in log(f)].count("outline"), 2)
        self.assertEqual([c["stage"] for c in log(f)].count("outline_review"), 2)
        st = rec["stages"]["outline_review"]
        self.assertEqual(st["unresolvedMustFix"], 1)
        self.assertTrue(st["rounds"][0]["sentBackForRevision"])
        self.assertEqual(rec["stages"]["outline"]["feedback"][0]["text"].count("time is tight"), 1)

    def test_an_outline_repaired_by_hand_can_be_reviewed_without_being_rewritten(self):
        """On the ordinary route a must-fix sends the outline back to the writer once, which is right while the
        outline is the writer's. The acceptance course's outline carries three repairs made by hand, recorded
        under repairedOutsideTheWriter; rewriting it to answer a finding nobody had read yet would throw them
        away. Asked for review only, Loom reports what the reviewer found and changes nothing."""
        f, cid, rec = begin("review-only", ol="must")
        outline_calls = [c["stage"] for c in log(f)].count("outline")
        before = copy.deepcopy(rec["stages"]["outline"]["output"])
        before["repairedOutsideTheWriter"] = [{"what": "a repair a person made", "by": "the implementer"}]
        r = engine.runner("pipe", cid).load()
        r["stages"]["outline"]["output"] = before
        engine.runner("pipe", cid).save(r)

        rec = go(cid, "review_outline")
        after = rec["stages"]["outline"]["output"]
        self.assertEqual(after, before, "the outline is untouched, word for word")
        self.assertEqual(after["repairedOutsideTheWriter"], [{"what": "a repair a person made", "by": "the implementer"}])
        self.assertEqual([c["stage"] for c in log(f)].count("outline"), outline_calls,
                         "the writer was not asked to write it again")
        st = rec["stages"]["outline_review"]
        self.assertEqual(st["status"], "done")
        self.assertTrue(st["reviewedWithoutRevising"])
        self.assertEqual(st["unresolvedMustFix"], 1, "and what the reviewer found is reported, not hidden")
        self.assertFalse(st["rounds"][-1].get("sentBackForRevision"))
        self.assertEqual(rec["status"], "waiting_approval", "reviewing is not approving")
        self.assertFalse(rec["stages"]["outline"].get("approved"))

    def test_a_review_only_run_says_which_outline_it_judged(self):
        from loom_server.engine import content_print
        from loom_server import pipeline as P
        f, cid, rec = begin("review-only-fp", ol="must")
        rec = go(cid, "review_outline")
        st = rec["stages"]["outline_review"]
        o, m = rec["stages"]["outline"]["output"], rec["stages"]["map"]["output"]
        self.assertEqual(st["inputFingerprint"], content_print({"outline": o, "coverage": P.coverage(o, m)}),
                         "a review is current only for the exact outline it read")
        self.assertEqual(st["appliedToFingerprint"], st["inputFingerprint"])

    def test_a_full_course_runs_to_the_end_with_projects_assets_and_independent_time(self):
        f, cid, rec = begin("full")
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"], acknowledged=["a"])
        self.assertEqual(rec["status"], "done")
        st = rec["stages"]
        self.assertEqual(st["outline"]["approved_map"]["nodes"][0]["name"], "Python")
        self.assertEqual(st["outline"]["acknowledged"], ["a"])
        sess = [u["output"] for u in st["materials"]["sessions"]]
        self.assertEqual([s["independent_work"]["minutes"] for s in sess], [30, 30, 30, 30])
        self.assertEqual(sess[0]["teaches_nodes"], ["N3"])
        # the supplied code was really run, on the supplied data
        chk = st["materials"]["sessions"][0]["assetChecks"]
        self.assertEqual([(c["name"], c["level"]) for c in chk], [("count.py", "executed")])
        self.assertEqual(chk[0]["output"].strip(), "rows 3")
        self.assertEqual([u["status"] for u in st["projects"]["units"]], ["done", "done"])
        self.assertEqual(st["projects"]["units"][1]["output"]["time"], {"live": 30, "independent": 40})
        self.assertEqual(st["review"]["status"], "done")
        self.assertEqual(len(st["review"]["output"]["areas"]), 10)
        stages = [c["stage"] for c in log(f)]
        self.assertEqual(stages[stages.index("materials"):], ["materials"] * 4 + ["project"] * 2 + ["review"])
        # the review is bound to the sessions and the projects together
        self.assertTrue(st["review"]["inputFingerprint"])
        self.assertIn("P1", json.dumps(st["review"]["output"]))

    def test_code_that_fails_is_sent_back_and_when_it_still_fails_the_session_is_not_filled_in(self):
        f, cid, rec = begin("badcode", code="raise SystemExit(3)\n")
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])
        self.assertEqual(rec["status"], "paused")
        u = rec["stages"]["materials"]["sessions"][0]
        self.assertEqual(u["status"], "failed")
        self.assertNotIn("output", u)
        self.assertIn("Running the code", rec["pause"]["detail"])

    def test_an_interrupted_research_resumes_without_repeating_the_batches_already_done(self):
        f = plan_file("resume", variant={}, fail={"4": "limit"})  # call 4 is the node batch: map, foundation review, approach, then this
        cid = new_course("resume")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d", pipeline=2)
        self.assertEqual(rec["status"], "paused")
        self.assertEqual(rec["pause"]["kind"], "limit")
        done = [b["key"] for b in rec["stages"]["research"]["batches"] if b["status"] == "done"]
        self.assertEqual(done, ["approach"])
        rec = go(cid, "resume")
        self.assertEqual(rec["status"], "waiting_approval")
        stages = [c["stage"] for c in log(f)]
        self.assertEqual(stages.count("map"), 1)
        self.assertEqual(stages.count("foundation_review"), 1)
        self.assertEqual(stages.count("research"), 3)  # approach, the node batch that was stopped, the node batch again


class NotHardCoded(unittest.TestCase):
    def test_the_prompts_that_build_the_map_and_judge_it_name_no_subject_of_any_test_course(self):
        from loom_server import prompts
        brief = {"topics": ["Beekeeping", "Storytelling"], "outcome": "x"}
        plan = dict(PLAN)
        bees = {"nodes": [node("N1", "Beekeeping", "requested"), node("N2", "Hive safety", needed=["N1"])]}
        texts = [prompts.topic_map(brief, plan, pipeline.project_policy(plan), pipeline.accounting(plan))[0], prompts.foundation_review(brief, plan, bees)[0],
                 prompts.research_nodes(brief, bees, ["N1"], [], "nodes-1")[0], prompts.source_review(brief, bees, [], [], False)[0]]
        for t in texts:
            low = t.lower()
            for word in ("python", "matplotlib", "pandas", "environment", "air quality", "birds", "budget", "design thinking", "spreadsheet"):
                self.assertNotIn(word, low, word)

    def test_a_map_for_an_unrelated_topic_is_judged_by_the_same_rules(self):
        m = {"nodes": [node("N1", "Beekeeping", "requested", req=["N2"]), node("N2", "Hive safety", needed=["N1"], req=["N3"]), node("N3", "Bee behaviour", needed=["N2"])], "outcome_needs": [], "assumed_entry": [], "stop_reason": "", "unresolved": []}
        b = {"topics": ["Beekeeping"]}
        self.assertEqual(pipeline.check_map(m, b), [])
        m["nodes"][2]["requires"] = ["N1"]
        self.assertTrue(any("circle" in x for x in pipeline.check_map(m, b)))

    def test_too_little_time_for_the_map_is_surfaced_and_never_fitted_by_shrinking_it(self):
        m = pipeline.derive_map({"nodes": [node("N1", "Beekeeping", "requested", est=200, req=["N2"]), node("N2", "Hive safety", needed=["N1"], est=200)]})
        o = {"sessions": [{"title": "s", "teaches": ["N2"], "practises": [], "independent_work": {"minutes": 0, "tasks": []}}, {"title": "t", "teaches": ["N1"], "practises": [], "independent_work": {"minutes": 0, "tasks": []}}], "projects": [], "deferred": [], "time_conflict": {"exists": False, "explanation": "", "options": []}}
        short = {"sessions": 2, "minutes": [15, 15], "unit": "Meeting", "total": 30, "weekly": False}
        p = pipeline.check_outline_v2(o, m, {"topics": ["Beekeeping"]}, short)
        self.assertTrue(any("time_conflict" in x for x in p), p)
        self.assertEqual(m["derived"]["requiredMinutes"], 400, "the map's own estimate is not changed to suit the time")


class ReviewFindings(unittest.TestCase):
    """Defects an independent reviewer reproduced on the first build of the pipeline. Each has its own check."""

    def test_names_in_other_scripts_and_with_symbols_are_not_collapsed(self):
        self.assertNotEqual(pipeline.norm("C++"), pipeline.norm("C#"))
        self.assertNotEqual(pipeline.norm("पायथन"), pipeline.norm("चार्ट"))
        self.assertEqual(pipeline.norm("Data-cleaning "), pipeline.norm("data cleaning"))
        m = {"nodes": [node("N1", "पायथन", "requested"), node("N2", "चार्ट", "requested")]}
        self.assertEqual(pipeline.check_map(m, {"topics": ["पायथन", "चार्ट"]}), [])

    def test_a_faithful_extract_with_thousands_separators_and_csv_commas_is_recognised(self):
        page = "Year 2001 count 1,412 ; year 2002 count 1,530 ; year 2003 count 1,377 ; year 2004 count 1,602"
        a = {"name": "c.csv", "kind": "dataset", "provenance": "public_source", "source_id": "S1", "content": "year,count\n2001,1412\n2002,1530\n2003,1377\n2004,1602\n"}
        self.assertEqual(pipeline._numbers(a["content"]), ["2001", "1412", "2002", "1530", "2003", "1377", "2004", "1602"])
        self.assertEqual(pipeline.origin_checks([a], {"S1": page})[0]["level"], "origin_unverified")
        self.assertEqual(pipeline.origin_checks([a], {"S1": "nothing like it, 12 and 99 only"})[0]["level"], "origin_failed")

    def test_asset_names_that_cannot_be_files_are_refused_before_anything_is_written(self):
        for bad in ["a\x00b.csv", "x" * 300 + ".csv", "_asset_under_test.py", "has space.csv", "../x.csv"]:
            self.assertTrue(pipeline.check_assets([{"name": bad, "kind": "document", "content": "x"}], "A"), repr(bad)[:30])

    def test_a_topic_marked_requested_must_be_one_the_team_asked_for_and_excluded_topics_are_not_taught(self):
        m = good_map()
        m["nodes"].append(node("N5", "Extra", "requested", needed=["OUTCOME"]))
        self.assertTrue(any("did not ask for it" in x for x in pipeline.check_map(m, BRIEF)))
        o = good_outline()
        o["sessions"][0]["teaches"] = ["N3", "N4"]  # N4 is already known
        self.assertTrue(any("already known" in x for x in pipeline.check_outline_v2(o, pipeline.derive_map(good_map()), BRIEF, PLAN)))

    def test_a_project_may_not_hand_learners_a_solution_and_its_facts_are_held_to_the_same_rules_as_a_sessions(self):
        unit = {"available_after_session": 2, "nodes_required": [], "minutes": {"live": 10, "independent": 10}}
        out = {"title": "t", "purpose": "p", "learner_brief": "b", "feedback_route": "f", "revision_route": "r", "example_or_solution_guidance": "g", "deliverables": ["d"],
               "milestones": [{"session": 2, "what": "a", "check": "c", "minutes": 10}, {"session": 3, "what": "b", "check": "c", "minutes": 10}], "prerequisites": [],
               "rubric": [{"criterion": c, "levels": [{"level": l, "descriptor": "d"} for l in "abc"]} for c in "xyz"], "time": {"live": 10, "independent": 10},
               "inputs": [], "claims": [{"text": "A fact", "type": "fact", "sources": ["S1"], "support": "stated_by_source", "note": ""}]}
        m = pipeline.derive_map(good_map())
        self.assertEqual(pipeline.check_project(out, unit, m, {}, {"S1": "direct"}), [])
        self.assertTrue(any("only in part" in x for x in pipeline.check_project(dict(out, claims=[dict(out["claims"][0], support="partly")]), unit, m, {}, {"S1": "direct"})))
        self.assertTrue(any("supporting it only in part" in x for x in pipeline.check_project(out, unit, m, {}, {"S1": "background"})))
        self.assertTrue(any("solution or a rubric" in x for x in pipeline.check_project(dict(out, inputs=[{"name": "s.py", "kind": "solution", "content": "x"}]), unit, m, {}, {"S1": "direct"})))

    def test_only_python_is_run_and_anything_else_is_reported_as_not_run(self):
        r = pipeline.run_assets([{"name": "a.js", "kind": "code", "run": "run", "content": "console.log(1)"}], [])
        self.assertEqual(r[0]["level"], "not_run")


@unittest.skipUnless(pipeline.sandbox_available(), "no sandbox on this computer")
class SandboxHolds(unittest.TestCase):
    """What the first build's sandbox let through, as an independent reviewer showed. Each now fails."""

    def run_code(self, code, files=None):
        return pipeline.run_python(code, files or {}, timeout=15)

    def test_it_cannot_start_another_program_or_ask_the_system_to(self):
        r = self.run_code("import subprocess\nsubprocess.run(['/usr/bin/touch', '%s/spawned'])\n" % TMP)
        self.assertEqual(r["state"], "failed")
        self.assertFalse((Path(TMP) / "spawned").exists())
        r = self.run_code("import os\nos.system('/usr/bin/open -g -j /System/Applications/Calculator.app')\nprint('ran')\n")
        self.assertNotIn("ran\n", (r.get("output") or "") + "x" if r["state"] != "ran" else "")

    def test_it_cannot_read_other_files_in_the_users_folders_or_temporary_folders(self):
        secret = Path(TMP) / "secret.txt"
        secret.write_text("TOPSECRET-123")
        for path in (str(secret), str(Path.home() / ".claude"), "/etc/../Users"):
            r = self.run_code("print(open(%r).read() if not %r.endswith('claude') and 'Users' not in %r else __import__('os').listdir(%r))\n" % (path, path, path, path))
            self.assertEqual(r["state"], "failed", path)
            self.assertNotIn("TOPSECRET", r.get("output", ""))

    def test_it_cannot_signal_other_processes_and_leaves_nothing_running(self):
        import subprocess as sp
        victim = sp.Popen(["/bin/sleep", "30"])
        try:
            r = self.run_code("import os, signal\ntry:\n    os.kill(%d, signal.SIGKILL); print('KILLED')\nexcept OSError as e:\n    print('blocked')\n" % victim.pid)
            self.assertIn("blocked", r.get("output", ""))
            self.assertIsNone(victim.poll())
        finally:
            victim.kill()

    def test_a_link_put_where_the_output_is_written_is_never_followed_by_the_parent(self):
        secret = Path(TMP) / "parent-secret.txt"
        secret.write_text("PARENT-ONLY-SECRET")
        r = self.run_code("import os\nos.remove('_stdout.txt')\nos.symlink(%r, '_stdout.txt')\nprint('x')\n" % str(secret))
        self.assertNotIn("PARENT-ONLY-SECRET", (r.get("output") or "") + (r.get("error") or ""))

    def test_endless_output_is_capped_and_the_run_is_stopped_on_time(self):
        import time as tm
        t0 = tm.time()
        r = pipeline.run_python("while True:\n    print('a' * 1000)\n", {}, timeout=3)
        self.assertEqual(r["state"], "failed")
        self.assertLess(tm.time() - t0, 15)
        self.assertLessEqual(len(r.get("output", "")), 1500)


class IdeaDates(unittest.TestCase):
    def test_a_date_must_be_on_the_page_the_ai_says_it_read(self):
        page = "Published 3 March 2026. Enrolment in short courses doubled this year."
        self.assertTrue(engine.date_on_page("3 March 2026", page))
        self.assertTrue(engine.date_on_page("March 2026", page))
        self.assertFalse(engine.date_on_page("3 March 2025", page))
        self.assertFalse(engine.date_on_page("14 July 2026", page))
        self.assertFalse(engine.date_on_page("recently", page))
        self.assertIsNone(engine.date_on_page("3 March 2026", ""))

    def test_an_idea_whose_only_date_is_not_on_its_page_is_not_backed_and_the_page_text_is_kept(self):
        trace = {"fetched": ["https://e.org/a"], "fetches": [{"url": "https://e.org/a", "state": "retrieved", "text": "Published 3 March 2026. Enrolment doubled."}], "searches": []}
        out = {"searched_on": "2026-09-29", "ideas": [
            {"idea": "Right date", "evidence": [{"url": "https://e.org/a", "dated": "3 March 2026", "title": "t", "publisher": "p", "what_it_says": "x"}]},
            {"idea": "Wrong date", "evidence": [{"url": "https://e.org/a", "dated": "9 June 2026", "title": "t", "publisher": "p", "what_it_says": "x"}]}], "shortfall": "", "not_opened": []}
        r = engine.finish_ideas(out, trace, "trending", "")
        self.assertEqual([i["backed"] for i in r["ideas"]], [True, False])
        self.assertTrue(r["ideas"][0]["evidence"][0]["dateOnPage"])
        self.assertIn("Enrolment doubled", r["ideas"][0]["evidence"][0]["retrievedExcerpt"])
        self.assertEqual(r["unbacked"], ["Wrong date"])


class InterpreterProbe(unittest.TestCase):
    def test_a_probe_that_exits_with_an_error_or_prints_nothing_is_never_read_as_nothing_missing(self):
        import stat
        d = Path(TMP) / "fakepy"
        d.mkdir(exist_ok=True)
        bad = d / "python-licence"
        bad.write_text("#!/bin/sh\necho 'licence not accepted' >&2\nexit 69\n")
        bad.chmod(bad.stat().st_mode | stat.S_IEXEC)
        silent = d / "python-silent"
        silent.write_text("#!/bin/sh\nexit 0\n")
        silent.chmod(silent.stat().st_mode | stat.S_IEXEC)
        for py in (str(bad), str(silent), "/nonexistent/python"):
            self.assertFalse(pipeline.usable(py), py)
            self.assertIsNone(pipeline.can_import(py, {"csv"}), "stdlib-only code still needs a usable interpreter")
            self.assertIsNone(pipeline.can_import(py, {"a_library_nobody_has"}))

    def test_when_no_interpreter_is_usable_the_code_is_reported_as_not_run(self):
        orig = pipeline._interpreters
        pipeline._interpreters = lambda: []
        try:
            r = pipeline.run_python("print(1)\n", {})
        finally:
            pipeline._interpreters = orig
        self.assertEqual(r["state"], "not_run")
        self.assertIn("no Python interpreter", r["reason"])

    def test_reserved_runtime_file_names_are_refused_as_inputs(self):
        for bad in ("_stdout.txt", "_stderr.txt", "_asset_under_test.py"):
            self.assertEqual(pipeline.run_python("print(1)\n", {bad: "x"})["state"], "failed", bad)


class AuditFindingsFromCodex(unittest.TestCase):
    """Defects an independent audit reproduced after the first review round."""

    def check(self, o, plan=PLAN, m=None):
        return pipeline.check_outline_v2(o, m or pipeline.derive_map(good_map()), BRIEF, plan)

    def test_project_minutes_are_placed_and_each_budget_is_held_separately(self):
        o = good_outline()
        o["projects"][0]["milestones"][0].update(live_minutes=100)  # 100 live minutes in a 60-minute session
        o["projects"][0]["minutes"]["live"] = 100
        p = self.check(o)
        self.assertTrue(any("Session 3 is 60 minutes, but projects place 100 live minutes" in x for x in p), p)
        o = good_outline()
        o["projects"][1]["milestones"][0].update(independent_minutes=70)
        o["projects"][1]["minutes"]["independent"] = 70
        p = self.check(o)
        self.assertTrue(any("Week 2's independent budget is 60" in x for x in p), p)
        no_ind = dict(PLAN)
        no_ind.pop("independent")
        o = good_outline()
        for sn in o["sessions"]:
            sn["independent_work"] = {"minutes": 0, "tasks": []}
        self.assertTrue(any("no independent time" in x for x in self.check(o, no_ind)))
        o = good_outline()
        o["projects"][0]["minutes"]["live"] = 25  # says 25, the milestones place 20
        self.assertTrue(any("must agree" in x for x in self.check(o)))

    def test_a_taught_topic_whose_required_prerequisite_is_deferred_is_refused(self):
        o = good_outline()
        o["sessions"][0]["teaches"] = []          # N3 is not taught: deferred
        o["deferred"] = [{"node": "N3", "reason": "no time"}]
        o["time_conflict"] = {"exists": True, "explanation": "x", "options": [{"label": "a", "effect": ""}, {"label": "b", "effect": ""}]}
        p = self.check(o)
        self.assertTrue(any("which is deferred, so it is not available" in x for x in p), p)

    def test_deferred_and_taught_are_different_things_and_trimmed_must_be_taught(self):
        o = good_outline()
        o["deferred"] = [{"node": "N3", "reason": "x"}]
        self.assertTrue(any("deferred and is also taught" in x for x in self.check(o)))
        o = good_outline()
        o["trimmed"] = [{"node": "N2", "minutes_given": 20, "reason": "less time"}]
        self.assertEqual([x for x in self.check(o) if "trimmed" in x], [])
        o["trimmed"] = [{"node": "N4", "minutes_given": 5, "reason": "x"}]
        self.assertTrue(any("no session teaches it" in x for x in self.check(o)))

    def test_setup_must_say_where_its_minutes_are_counted_and_extra_time_must_be_declared(self):
        o = good_outline()
        o["setup"] = {"minutes": 60, "counted_in": "separate_extra", "what": "install"}
        self.assertTrue(any("extra time" in x for x in self.check(o)))
        o["setup"] = {"minutes": 60, "counted_in": "independent_week_1", "what": "install"}
        self.assertEqual([x for x in self.check(o) if "Week 1's independent budget" in x], [], "60 minutes of setup fit inside the week's 60")
        o["setup"] = {"minutes": 90, "counted_in": "independent_week_1", "what": "install"}
        self.assertTrue(any("Week 1's independent budget is 60 minutes, but projects and setup place 90" in x for x in self.check(o)))

    def test_a_verdict_belongs_to_one_claim_on_one_page_not_to_the_whole_page(self):
        a = {"url": "https://e.org/doc", "claim": "Supported claim", "strength": "direct", "limits": ""}
        b = {"url": "https://e.org/doc/", "claim": "An unsupported claim", "strength": "direct", "limits": ""}
        self.assertNotEqual(pipeline.claim_key(a), pipeline.claim_key(b))
        self.assertEqual(pipeline.claim_key(a), pipeline.claim_key(dict(a, claim="supported  CLAIM")))

    def test_an_audit_that_cannot_tell_or_did_not_judge_never_leaves_direct_support_standing(self):
        s = {"strength": "direct", "limits": ""}
        for v in ("cannot_tell", None):
            e = pipeline.source_effect(s, v)
            self.assertEqual(e["strength"], "partial")
            self.assertTrue(e["auditUnresolved"])


class PreparedFiles(unittest.TestCase):
    PV = {"publisher": "NASA", "publisherUrl": "https://example.org", "requestUrl": "https://example.org/x", "retrievedAt": "2026-09-29T15:00:00Z", "serviceVersion": "v2.10.0",
          "licenceNote": "none stated", "fields": [{"name": "T2M", "units": "C"}], "coverage": {"years": "2017-2026"}, "limitations": ["reanalysis"]}

    def course(self, name):
        cid = new_course(name)
        plan_file(name)
        go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d", pipeline=2)
        return cid

    def test_an_original_is_kept_exactly_with_its_checksum_and_can_never_be_replaced(self):
        cid = self.course("prep1")
        out = engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a,b\n1,2\n", "provenance": dict(self.PV), "purpose": "raw"}])
        import hashlib
        self.assertEqual(out[0]["sha256"], hashlib.sha256(b"a,b\n1,2\n").hexdigest())
        with self.assertRaises(storage.StoreError):
            engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a,b\n9,9\n", "provenance": dict(self.PV)}])
        with self.assertRaises(storage.StoreError):
            engine.register_prepared("pipe", cid, [{"name": "p.csv", "kind": "original", "text": "x\n", "provenance": dict(self.PV, sha256="0" * 64)}])
        with self.assertRaises(storage.StoreError):
            engine.register_prepared("pipe", cid, [{"name": "q.csv", "kind": "original", "text": "x\n", "provenance": {"publisher": "NASA"}}])
        with self.assertRaises(storage.StoreError):
            engine.register_prepared("pipe", cid, [{"name": "r.csv", "kind": "original", "text": "x\n", "provenance": dict(self.PV, transformation="removed rows")}])
        rec = engine.runner("pipe", cid).load()
        assets = engine.prepared_assets("pipe", cid, rec)
        self.assertEqual([(a["name"], a["kind"], a["prepared"]) for a in assets], [("o.csv", "dataset", True)])
        self.assertEqual(engine.prepared_digest("pipe", cid, rec)[0]["the_file_starts_with"], ["a,b", "1,2"])

    def test_a_prepared_file_is_found_by_name_so_a_backup_restored_elsewhere_still_delivers_it(self):
        """A record that still carries an absolute path from another machine must not decide where the bytes are read from."""
        cid = self.course("prep-portable")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a,b\n1,2\n", "provenance": dict(self.PV), "purpose": "raw"}])
        r = engine.runner("pipe", cid)
        rec = r.load()
        self.assertNotIn("path", rec["prepared"][0])  # nothing machine-specific is written down
        rec["prepared"][0]["path"] = "/Volumes/SomeOtherMac/gone/o.csv"  # as an older record, or one restored from a backup, would hold
        r.save(rec)
        rec = r.load()
        self.assertEqual(engine.prepared_assets("pipe", cid, rec)[0]["content"], "a,b\n1,2\n")
        self.assertEqual(engine.prepared_digest("pipe", cid, rec)[0]["the_file_starts_with"], ["a,b", "1,2"])

    def test_a_prepared_file_name_can_never_reach_outside_its_own_course_folder(self):
        cid = self.course("prep-confined")
        for bad in ("../escape.csv", "sub/o.csv", "/etc/passwd", "..", ".hidden"):
            with self.assertRaises(storage.StoreError):
                storage.prepared_path("pipe", cid, bad)
            with self.assertRaises(storage.StoreError):
                engine.register_prepared("pipe", cid, [{"name": bad, "kind": "original", "text": "x\n", "provenance": dict(self.PV)}])

    def test_a_registered_file_whose_bytes_are_gone_is_reported_not_passed_over_in_silence(self):
        """A writer must never be told a dataset is in hand when it is not."""
        cid = self.course("prep-missing")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])
        rec = engine.runner("pipe", cid).load()
        storage.prepared_path("pipe", cid, "o.csv").unlink()
        for call in (engine.prepared_assets, engine.prepared_digest):
            with self.assertRaises(storage.StoreError) as e:
                call("pipe", cid, rec)
            self.assertIn("o.csv", str(e.exception))

    def test_a_symlink_or_a_file_that_does_not_match_its_checksum_is_never_read(self):
        """Harmless sentinels only: nothing real is pointed at."""
        import os
        cid = self.course("prep-tamper")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])
        rec = engine.runner("pipe", cid).load()
        f = storage.prepared_path("pipe", cid, "o.csv")
        outside = f.parent.parent / "sentinel.txt"
        outside.write_text("SENTINEL-NOT-A-PREPARED-FILE\n")
        f.unlink()
        os.symlink(outside, f)
        with self.assertRaises(storage.StoreError):
            engine.prepared_assets("pipe", cid, rec)  # a link never stands in for a kept file
        f.unlink()
        f.write_text("a\n9\n")  # right name, different bytes
        with self.assertRaises(storage.StoreError) as e:
            engine.prepared_assets("pipe", cid, rec)
        self.assertIn("checksum", str(e.exception))

    def test_a_backup_carries_its_prepared_bytes_so_a_restore_stands_on_its_own(self):
        cid = self.course("prep-backup")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a,b\n1,2\n", "provenance": dict(self.PV)}])
        b = storage.backup("pipe", cid)
        self.assertEqual([x["name"] for x in b["prepared"]], ["o.csv"])
        storage.prepared_path("pipe", cid, "o.csv").unlink()  # the original course's file is gone
        meta = storage.restore("pipe", b)
        new_cid = meta["id"]
        self.assertNotEqual(new_cid, cid)
        rec = engine.runner("pipe", new_cid).load()
        self.assertNotIn("path", rec["prepared"][0])
        self.assertEqual(engine.prepared_assets("pipe", new_cid, rec)[0]["content"], "a,b\n1,2\n")

    def test_a_restore_never_carries_a_path_from_another_course_or_machine(self):
        cid = self.course("prep-foreign")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])
        b = storage.backup("pipe", cid)
        b["engine"]["prepared"][0]["path"] = "/Volumes/Other/another-course/prepared/o.csv"
        new_cid = storage.restore("pipe", b)["id"]
        rec = engine.runner("pipe", new_cid).load()
        self.assertNotIn("path", rec["prepared"][0])
        self.assertTrue(storage.prepared_path("pipe", new_cid, "o.csv").is_file())
        self.assertEqual(engine.prepared_assets("pipe", new_cid, rec)[0]["content"], "a\n1\n")

    def test_a_backup_whose_prepared_bytes_are_absent_is_restored_as_missing_not_as_present(self):
        cid = self.course("prep-nobytes")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])
        b = storage.backup("pipe", cid)
        b["prepared"] = []  # an older backup, made before bytes were carried
        new_cid = storage.restore("pipe", b)["id"]
        rec = engine.runner("pipe", new_cid).load()
        self.assertTrue(rec["prepared"][0]["bytesMissing"])
        with self.assertRaises(storage.StoreError):
            engine.prepared_assets("pipe", new_cid, rec)

    def test_a_copy_of_a_course_gets_its_own_prepared_files(self):
        cid = self.course("prep-copy")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n7\n", "provenance": dict(self.PV)}])
        new_cid = storage.duplicate_course("pipe", cid)["id"]
        storage.prepared_path("pipe", cid, "o.csv").unlink()  # the source course's file is gone
        rec = engine.runner("pipe", new_cid).load()
        self.assertEqual(engine.prepared_assets("pipe", new_cid, rec)[0]["content"], "a\n7\n")

    def test_a_backup_carries_binary_bytes_exactly_and_never_through_a_lossy_decode(self):
        """A synthetic PDF-like sentinel: bytes that are not valid UTF-8 must survive backup and restore unchanged."""
        import hashlib
        cid = self.course("prep-binary")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])
        blob = b"%PDF-1.4\n\xff\xfe\x00\x01\x80\x81binary-sentinel\x00\xed\xa0\x80\n%%EOF\n"
        self.assertRaises(UnicodeDecodeError, blob.decode, "utf-8")  # the old path would have replaced these
        storage.prepared_path("pipe", cid, "s.pdf", make=True).write_bytes(blob)
        b = storage.backup("pipe", cid)
        item = next(x for x in b["prepared"] if x["name"] == "s.pdf")
        self.assertEqual(item["encoding"], "binary")
        self.assertNotIn("text", item)
        self.assertEqual(item["sha256"], hashlib.sha256(blob).hexdigest())
        new_cid = storage.restore("pipe", b)["id"]
        self.assertEqual(storage.prepared_path("pipe", new_cid, "s.pdf").read_bytes(), blob)
        self.assertEqual(storage.read_prepared("pipe", new_cid, "s.pdf", item["sha256"]), blob)

    def test_bytes_that_do_not_match_the_checksum_they_arrive_with_are_never_written(self):
        cid = self.course("prep-badbytes")
        engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])
        b = storage.backup("pipe", cid)
        b["prepared"][0]["b64"] = "dGFtcGVyZWQ="  # "tampered", against the recorded checksum
        new_cid = storage.restore("pipe", b)["id"]
        rec = engine.runner("pipe", new_cid).load()
        self.assertTrue(rec["prepared"][0]["bytesMissing"])
        with self.assertRaises(storage.StoreError):
            engine.prepared_assets("pipe", new_cid, rec)

    def test_a_teaching_copy_is_described_by_its_own_bytes_not_by_the_original_s_description(self):
        """Codex found every cleaned long-form file still saying "wide, 20 data rows, ten fill codes, 13 header
        lines", inherited from the original it came from, and that description travelled into writer prompts."""
        cid = self.course("prep-measured")
        wide = "-BEGIN HEADER-\nsomething\n-END HEADER-\nPARAMETER,YEAR,JAN,FEB\nT2M,2017,20.1,-999.00\nT2M,2018,21.2,22.3\n"
        described = dict(self.PV, coverage={"layout": "wide: one row per measure per year", "rows": "20 data rows", "header": "13 header lines"})
        o = engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": wide, "provenance": described}])[0]
        self.assertEqual(o["measured"]["preambleLinesBeforeTheColumnNames"], 3, "counted, not taken from the description of 13")
        self.assertEqual(o["measured"]["dataRows"], 2)
        self.assertEqual(o["measured"]["fillCodeMinus999Values"], 1, "-999.00 is the publisher's fill code")
        self.assertEqual(o["measured"]["columnNames"], ["PARAMETER", "YEAR", "JAN", "FEB"])

        long_form = "PARAMETER,YEAR,MONTH,MONTH_NUM,VALUE\nT2M,2017,JAN,1,20.1\nT2M,2018,JAN,1,21.2\nT2M,2018,FEB,2,22.3\n"
        t = engine.register_prepared("pipe", cid, [{"name": "t.csv", "kind": "teaching_copy", "text": long_form,
            "provenance": {**described, "derivedFromSha256": o["sha256"], "transformationLog": ["reshaped to long form", "dropped fill codes"], "plantedProblems": False}}])[-1]
        self.assertEqual(t["measured"]["dataRows"], 3, "its own rows, not the original's 20")
        self.assertEqual(t["measured"]["preambleLinesBeforeTheColumnNames"], 0)
        self.assertEqual(t["measured"]["fillCodeMinus999Values"], 0, "the fill codes really are gone")
        self.assertIn("long", t["measured"]["layout"])
        self.assertEqual(t["provenance"]["coverage"]["rows"], "20 data rows", "the description it was registered with is kept, separately")

        # and a writer is shown the measurement beside the description, not the description alone
        rec = engine.runner("pipe", cid).load()
        d = {x["name"]: x for x in engine.prepared_digest("pipe", cid, rec)}["t.csv"]
        self.assertEqual(d["what_loom_counted_in_this_file"]["dataRows"], 3)
        self.assertIn("how_it_was_described_when_registered", d)
        self.assertNotIn("provenance", d, "the description is labelled as a description")

    def test_a_teaching_copy_names_its_original_logs_every_change_and_says_whether_problems_were_planted(self):
        cid = self.course("prep2")
        o = engine.register_prepared("pipe", cid, [{"name": "o.csv", "kind": "original", "text": "a\n1\n", "provenance": dict(self.PV)}])[0]
        bad = {"name": "t.csv", "kind": "teaching_copy", "text": "a\n1\n", "provenance": {"derivedFromSha256": o["sha256"], "transformationLog": ["blanked row 1"]}}
        with self.assertRaises(storage.StoreError):
            engine.register_prepared("pipe", cid, [bad])  # does not say whether problems were planted
        good = dict(bad, provenance=dict(bad["provenance"], plantedProblems=True))
        self.assertEqual(engine.register_prepared("pipe", cid, [good])[-1]["kind"], "teaching_copy")
        with self.assertRaises(storage.StoreError):
            engine.register_prepared("pipe", cid, [dict(good, name="u.csv", provenance=dict(good["provenance"], derivedFromSha256="f" * 64))])


import http.server
import threading


class Page(http.server.BaseHTTPRequestHandler):
    PDF_BYTES = None
    BODY = b"<html><head><style>x{}</style></head><body><h1>Tables</h1><p>A table has rows and columns. Each row is one record and each column one measurement.</p><script>var a=1</script></body></html>"

    def do_GET(self):
        if self.path == "/redirect-to-private":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if self.path in ("/gzipped", "/gzip-undeclared", "/broken-gzip", "/brotli"):
            import gzip as _gz
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if self.path == "/gzipped":
                self.send_header("Content-Encoding", "gzip")
            if self.path == "/broken-gzip":
                self.send_header("Content-Encoding", "gzip")
            if self.path == "/brotli":
                self.send_header("Content-Encoding", "br")
            self.end_headers()
            if self.path == "/broken-gzip":
                self.wfile.write(b"\x1f\x8b\x08\x00nonsense that is not a gzip stream at all")
            elif self.path == "/brotli":
                self.wfile.write(b"whatever brotli would be")
            else:
                # /gzip-undeclared sends the stream with NO Content-Encoding, as python.org did.
                self.wfile.write(_gz.compress(self.BODY))
            return
        if self.path in ("/pdf", "/pdf-real"):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(self.PDF_BYTES if self.path == "/pdf-real" and self.PDF_BYTES else b"%PDF-1.4 not really")
            return
        self.send_response(200 if self.path == "/page" else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.BODY if self.path == "/page" else b"no")

    def log_message(self, *a):
        pass


class DirectEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_a_page_sent_compressed_is_unpacked_rather_than_read_as_rubbish(self):
        """Loom asks for no encoding and python.org sent a gzip stream anyway. The compressed bytes were decoded
        as if they were the page: 9441 characters, 44% of them replacement characters, labelled direct_text and
        counted as retrieved evidence for a claim."""
        from loom_server import evidence
        for path in ("/gzipped", "/gzip-undeclared"):
            r = evidence.fetch_original(self.url(path), allow_local=True)
            self.assertTrue(r["ok"], path)
            self.assertEqual(r["textMethod"], "html_tags_removed", path)
            self.assertIn("A table has rows and columns", r["text"], f"{path} was unpacked and read")
            self.assertNotIn("\ufffd", r["text"], path)

    def test_bytes_that_do_not_read_as_text_are_never_kept_as_text(self):
        from loom_server import evidence
        r = evidence.fetch_original(self.url("/broken-gzip"), allow_local=True)
        self.assertFalse(r.get("text"), "nothing unreadable is kept")
        self.assertIn("could not be unpacked", r["note"])

        r2 = evidence.fetch_original(self.url("/brotli"), allow_local=True)
        self.assertFalse(r2.get("text"), "an encoding Loom cannot unpack keeps no text")
        self.assertIn("cannot unpack", r2["note"])

    def test_a_stream_decoded_as_text_is_recognised_as_not_being_text(self):
        import gzip as _gz
        from loom_server import evidence
        rubbish = _gz.compress(b"hello world " * 500).decode("utf-8", "replace")
        self.assertTrue(evidence._mostly_undecodable(rubbish))
        self.assertFalse(evidence._mostly_undecodable("This is an ordinary page of text. " * 100))
        self.assertFalse(evidence._mostly_undecodable("Ordinary text \ufffd with one bad byte. " * 100),
                         "a page with some mojibake in it is still a page")
        self.assertFalse(evidence._mostly_undecodable("short"), "too little to judge")

    def test_an_unreadable_page_cannot_become_direct_text_evidence(self):
        """S53 on the acceptance course held unreadable bytes and was labelled direct_text."""
        from loom_server import evidence
        fetched = evidence.fetch_original(self.url("/broken-gzip"), allow_local=True)
        s_ = evidence.upgrade({"quote": "a table has rows and columns"}, fetched)
        self.assertNotEqual(s_.get("evidenceLevel"), "direct_text")
        self.assertNotEqual(s_.get("evidenceLevel"), "direct_text_quote_found")

    def test_loom_keeps_the_checksum_of_what_came_back_and_extracts_text_by_a_stated_method(self):
        from loom_server import evidence
        r = evidence.fetch_original(self.url("/page"), allow_local=True)
        import hashlib
        self.assertTrue(r["ok"])
        self.assertEqual(r["sha256"], hashlib.sha256(Page.BODY).hexdigest())
        self.assertEqual(r["textMethod"], "html_tags_removed")
        self.assertIn("Each row is one record", r["text"])
        self.assertNotIn("var a=1", r["text"], "scripts are not text of the page")
        self.assertTrue(evidence.fetch_original(self.url("/redirect"), allow_local=True)["ok"], "a redirect is followed and every hop is checked")
        pdf = evidence.fetch_original(self.url("/pdf"), allow_local=True)
        self.assertEqual((pdf["ok"], pdf["textMethod"]), (True, "pdf_unsupported"), "a file that is not a readable PDF says so rather than guessing")
        self.assertEqual(evidence.fetch_original(self.url("/nope"), allow_local=True)["ok"], False)

    def test_a_private_address_is_never_fetched(self):
        from loom_server import evidence
        r = evidence.fetch_original("http://127.0.0.1:9/x", engine.is_public_host)
        self.assertFalse(r["ok"])
        self.assertIn("not on the public internet", r["note"])
        for bad in ("http://localhost:9/x", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/", "http://[::1]:9/x"):
            self.assertIn("not on the public internet", evidence.fetch_original(bad)["note"], bad)

    def test_a_redirect_towards_a_private_address_is_refused_at_that_hop(self):
        """Every hop is checked, so a public first host cannot hand the request on to a private one."""
        from loom_server import evidence
        r = evidence.fetch_original(self.url("/redirect-to-private"), allow_local=True)
        self.assertFalse(r["ok"])
        self.assertIn("not on the public internet", r["note"])
        self.assertEqual(r["addressesOpened"], ["127.0.0.1"], "it stopped at the hop it had already checked")

    def test_a_link_check_follows_redirects_through_the_same_safe_transport(self):
        import os as _os
        orig, skip = engine.ALLOW_LOCAL_FETCH, _os.environ.pop("LOOM_SKIP_LINK_CHECK", None)
        engine.ALLOW_LOCAL_FETCH = True
        try:
            self.assertTrue(engine.link_opens(self.url("/redirect"))["opened"])
            bad = engine.link_opens(self.url("/redirect-to-private"))
        finally:
            engine.ALLOW_LOCAL_FETCH = orig
            if skip is not None:
                _os.environ["LOOM_SKIP_LINK_CHECK"] = skip
        self.assertFalse(bad["opened"])
        self.assertIn("not on the public internet", bad["note"])

    def test_the_address_that_was_checked_is_the_address_that_is_opened(self):
        """A name that answers differently the second time cannot move the destination: mocked, never a live probe."""
        from loom_server import evidence
        import socket as _s
        calls = []
        real = evidence.socket.getaddrinfo

        def flip(host, *a, **k):
            calls.append(host)
            if host == "example.invalid":
                # public on the first answer, private on every answer after it
                addr = "93.184.216.34" if len(calls) == 1 else "127.0.0.1"
                return [(_s.AF_INET, _s.SOCK_STREAM, 6, "", (addr, 0))]
            return real(host, *a, **k)
        made = []
        real_conn = evidence.socket.create_connection

        def watch(addr, *a, **k):
            made.append(addr[0])
            raise OSError("not connected in a test")
        evidence.socket.getaddrinfo, evidence.socket.create_connection = flip, watch
        try:
            evidence.open_public("http://example.invalid/x", timeout=1)
        finally:
            evidence.socket.getaddrinfo, evidence.socket.create_connection = real, real_conn
        self.assertEqual(made, ["93.184.216.34"], "it connects to the address it checked, not to a later answer")

    def test_a_host_that_answers_with_both_a_public_and_a_private_address_is_opened_only_on_the_public_one(self):
        """A resolver really does return a stray link-local entry for ordinary publishers, so those answers are
        dropped rather than shutting the source out. Loom still never connects to one."""
        from loom_server import evidence
        import socket as _s
        real, real_conn = evidence.socket.getaddrinfo, evidence.socket.create_connection
        made = []

        def both(host, *a, **k):
            if host == "mixed.invalid":
                return [(_s.AF_INET6, _s.SOCK_STREAM, 6, "", ("fe80::1", 0, 0, 0)),
                        (_s.AF_INET, _s.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
                        (_s.AF_INET, _s.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
            return real(host, *a, **k)

        def watch(addr, *a, **k):
            made.append(addr[0])
            raise OSError("not connected in a test")
        evidence.socket.getaddrinfo, evidence.socket.create_connection = both, watch
        try:
            self.assertEqual([a for _f, a in evidence.global_addresses("mixed.invalid")], ["93.184.216.34"])
            evidence.open_public("http://mixed.invalid/x", timeout=1)
        finally:
            evidence.socket.getaddrinfo, evidence.socket.create_connection = real, real_conn
        self.assertEqual(made, ["93.184.216.34"], "only the public address is ever connected to")

    def test_a_host_with_no_public_address_at_all_is_refused(self):
        from loom_server import evidence
        import socket as _s
        real = evidence.socket.getaddrinfo

        def priv(host, *a, **k):
            if host == "private.invalid":
                return [(_s.AF_INET, _s.SOCK_STREAM, 6, "", ("10.0.0.5", 0)), (_s.AF_INET, _s.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
            return real(host, *a, **k)
        evidence.socket.getaddrinfo = priv
        try:
            r = evidence.open_public("http://private.invalid/x", timeout=1)
        finally:
            evidence.socket.getaddrinfo = real
        self.assertTrue(r["blocked"])
        self.assertIn("not on the public internet", r["note"])

    def _legacy(self, name, n=3, pages=2):
        """A course whose research predates identity fields, as the 113 acceptance records do."""
        from loom_server import evidence
        f, cid, rec = begin(name)
        r = engine.runner("pipe", cid).load()
        made = []
        for i in range(n):
            s_ = dict(r["stages"]["research"]["output"]["sources"][0])
            for field in ("authors", "published", "version_or_edition", "identifier", "role", "lineage"):
                s_.pop(field, None)
            s_.update(id=f"S{i}", url=f"https://e{i % pages}.example.org/doc", claim=f"claim number {i}")
            made.append(s_)
        r["stages"]["research"]["output"]["sources"] = made
        for b in r["stages"]["research"]["batches"]:
            b.setdefault("output", {})["sources"] = made
        r["stages"]["research"]["direct"] = {}
        r["stages"]["research"]["identity"] = {}
        engine.runner("pipe", cid).save(r)
        real = evidence.fetch_original
        evidence.fetch_original = lambda url, *a, **k: {"ok": True, "status": 200, "text": "A table has rows and columns. " * 20,
            "sha256": "a" * 63 + str(abs(hash(url)) % 10), "requestedUrl": url, "finalUrl": url, "textMethod": "plain_text",
            "bytes": 9, "contentType": "text/plain", "note": "", "attemptedAt": "2026-09-30T00:00:00Z",
            "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"}
        try:
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence"})
            wait(cid)
        finally:
            evidence.fetch_original = real
        return f, cid

    def test_identity_is_read_from_the_document_once_per_page_and_fills_legacy_records(self):
        """The acceptance records carry no identity keys at all, so an attribution review can only reject them.
        Identity is read out of the retrieved document instead, once per page however many claims rest on it."""
        f, cid = self._legacy("identity-legacy", n=6, pages=2)
        before = engine.runner("pipe", cid).load()
        self.assertTrue(all(not s.get("role") for s in before["stages"]["research"]["output"]["sources"]))
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        self.assertEqual(rs["identityProgress"]["pages"], 2, "one reading per page, not per claim")
        self.assertEqual(len(rs["identity"]), 2)
        calls = [c for c in log(f) if c["stage"] == "identity"]
        self.assertEqual(len(calls), 1, "six claims over two pages is one bounded request")
        for s_ in rs["output"]["sources"]:
            self.assertTrue(s_.get("authors"), "who made it now recorded")
            self.assertTrue(s_.get("published"))
            self.assertEqual(s_.get("role"), "official_documentation")
            self.assertTrue(s_["identityRead"]["wordsThatShowIt"], "with the words on the page that show it")

    def test_a_second_reading_skips_pages_already_read_and_redo_reads_them_again(self):
        f, cid = self._legacy("identity-resume", n=4, pages=2)
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        wait(cid)
        first = len([c for c in log(f) if c["stage"] == "identity"])
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        rec = wait(cid)
        self.assertEqual(len([c for c in log(f) if c["stage"] == "identity"]), first, "already read, so nothing repeated")
        self.assertEqual(rec["stages"]["research"]["identityProgress"]["pages"], 0)
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity", "redo": True})
        wait(cid)
        self.assertGreater(len([c for c in log(f) if c["stage"] == "identity"]), first, "redo reads them again")

    def test_identity_read_from_one_version_of_a_page_stops_applying_when_the_bytes_change(self):
        from loom_server import evidence, pipeline
        f, cid = self._legacy("identity-bytes", n=2, pages=1)
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        wait(cid)
        r = engine.runner("pipe", cid).load()
        self.assertTrue(r["stages"]["research"]["output"]["sources"][0].get("authors"))
        for k in r["stages"]["research"]["direct"]:
            r["stages"]["research"]["direct"][k]["sha256"] = "d" * 64   # the page was fetched again and differs
        for s_ in r["stages"]["research"]["output"]["sources"]:
            for field in ("authors", "published", "version_or_edition", "identifier", "role"):
                s_.pop(field, None)
        engine.runner("pipe", cid)._merge_research(r)
        got = r["stages"]["research"]["output"]["sources"][0]
        self.assertFalse(got.get("authors"), "identity read from different bytes no longer applies")
        self.assertNotIn("identityRead", got)

    def test_a_page_that_does_not_say_who_made_it_is_left_unknown_not_invented(self):
        f, cid = self._legacy("identity-unknown", n=2, pages=1)
        plan_file("identity-unknown", variant={"identity_all_unknown": True})
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        rec = wait(cid)
        s_ = rec["stages"]["research"]["output"]["sources"][0]
        self.assertFalse(s_.get("authors"), "nothing is invented")
        self.assertIn("authors", s_["identityRead"]["unknown"], "and it says so plainly")
        self.assertEqual(s_.get("role"), "secondary_aid")

    def test_a_title_belonging_to_another_work_is_replaced_and_a_paraphrase_is_only_flagged(self):
        """The attribution review found one record carrying another paper's title and one with an invented
        descriptive title. Cosmetic differences are far more common and must not be rewritten."""
        cases = [
            ("An Investigation Into Secondary School Students Debugging Behaviour",
             "Context-Specific Instruction: A Longitudinal Study of Something Else", "replace"),
            ("Colaboratory Frequently Asked Questions", "Google Colab FAQ", "replace"),
            ("Developing and deploying an integrated workshop curriculum teaching computational skills",
             "Teaching computational reproducibility / workshop delivery report", "flag"),
            ("pandas.read_csv", "pandas.read_csv — pandas API reference", "leave"),
            ("4. Using Python on Windows", "Using Python on Windows — Python 3 documentation", "leave"),
            ("Quick start guide", "Quick start guide (Matplotlib)", "leave"),
        ]
        for published, recorded, want in cases:
            overlap = engine._title_overlap(published, recorded)
            if want == "leave":
                self.assertTrue(overlap is None or overlap >= engine.TITLE_SAME,
                                f"left alone, whether by containment or by wording: {recorded!r} ({overlap})")
            elif want == "replace":
                self.assertIsNotNone(overlap)
                self.assertLess(overlap, engine.TITLE_DIFFERENT, recorded)
            else:
                self.assertIsNotNone(overlap)
                self.assertGreaterEqual(overlap, engine.TITLE_DIFFERENT, recorded)
                self.assertLess(overlap, engine.TITLE_SAME, recorded)

    def test_a_topic_is_not_supported_by_a_page_loom_never_retrieved_itself(self):
        """Fifteen acceptance records say fetch=retrieved while Loom holds no text from them: that is the model's
        own fetch tool returning a summary, which is not the page."""
        from loom_server import pipeline
        f, cid, rec = begin("standing-honest")
        r = engine.runner("pipe", cid).load()
        node = r["stages"]["map"]["output"]["nodes"][0]
        summary_only = dict(r["stages"]["research"]["output"]["sources"][0],
                            id="SX", node_ids=[node["id"]], fetch="retrieved", strength="direct",
                            retrievedExcerpt="a summary the fetch tool made")
        summary_only.pop("evidenceLevel", None)
        summary_only.pop("directRetrieval", None)
        summary_only.pop("directExcerpt", None)
        r["stages"]["research"]["output"]["sources"] = [summary_only]
        for b in r["stages"]["research"]["batches"]:
            b.setdefault("output", {})["sources"] = [summary_only]
        r["stages"]["research"]["direct"] = {}
        r["stages"]["research"]["node_findings"] = []
        engine.runner("pipe", cid)._merge_research(r)
        cov = {c["node"]: c["status"] for c in r["stages"]["research"]["output"]["nodeCoverage"]}
        self.assertNotEqual(cov.get(node["id"]), "supported",
                            "a tool summary is not support, however confidently the record says retrieved")

    def test_the_evidence_given_to_a_writer_is_bounded_and_relevant(self):
        """Passing every source's passages to the outline made that request 660,000 characters and it timed out
        after 30 minutes. Evidence must reach writers bounded, and per session where that is what is used."""
        from loom_server import prompts
        srcs = []
        for i in range(200):
            srcs.append({"id": f"S{i}", "title": f"Source {i}", "url": f"https://e{i}.example.org/p", "claim": f"claim {i}",
                         "node_ids": ["N1"] if i < 5 else ["N9"], "kind": "other", "strength": "direct",
                         "quote": "a quotation of some length here", "finding": "f",
                         "retrievedExcerpt": "T" * 3000, "directExcerpt": "P" * 3000,
                         "evidenceLevel": "direct_text_quote_found" if i < 50 else "tool_summary",
                         "directRetrieval": {"sha256": "a" * 64, "quoteVerbatim": i < 50}})
        research = {"sources": srcs}

        # the outline gets identity and standing, not the pages
        d = prompts.sources_digest(research, passage=0, summary=0, cap=prompts.OUTLINE_SOURCE_CAP)
        self.assertEqual(len(d), prompts.OUTLINE_SOURCE_CAP)
        self.assertTrue(all("the_original_text_loom_retrieved_itself" not in x for x in d), "no passages in the outline's copy")
        self.assertTrue(all("a_summary_made_by_a_tool" not in x for x in d))
        kept_strong = sum(1 for x in d if x["evidence_level"] == "direct_text_quote_found")
        self.assertEqual(kept_strong, 50, "every source with a verbatim quotation survives the cut")
        self.assertEqual(len(d) - kept_strong, prompts.OUTLINE_SOURCE_CAP - 50, "the weakest are what gets cut")

        # a session writer gets the passages, for the topics that session teaches
        one = prompts.sources_digest(research, only_nodes=["N1"], cap=prompts.SESSION_SOURCE_CAP)
        self.assertEqual(len(one), 5, "only the sources for this session's topics")
        self.assertTrue(all("the_original_text_loom_retrieved_itself" in x for x in one), "and it does get the passages")

        outline_out = {"sessions": [{"title": "t", "outcome": "o", "topics": [], "teaches": ["N1"], "practises": [],
                                     "independent_work": {"minutes": 0, "tasks": []}}], "course_outcome": "c", "final_evidence": "f"}
        prompt, _ = prompts.outline2(BRIEF, PLAN, {"nodes": []}, research, {"minor": 0, "major": 0, "note": ""},
                                     {"statement": "x"}, [], None, None, None) if False else prompts.materials2(
            BRIEF, PLAN, {"nodes": []}, research, outline_out, 0, None, [], [], {"minor": 0, "major": 0, "note": ""})
        self.assertLess(len(prompt), 200_000, "a session request stays a workable size")
        self.assertEqual(prompt.count("<sources>"), 1, "the sources block is not sent twice")

    def test_a_cap_never_removes_a_required_topic_s_only_support_and_says_what_it_left_out(self):
        """Codex found cap=60 cutting 17 of 77 matching quotations, and my report wrongly said none were cut. At
        cap=25 on the real data, eight required topics lost every source that supported them."""
        from loom_server import prompts
        # 40 well-evidenced sources on one popular topic, and one lone source for a required topic, placed last
        srcs = [{"id": f"P{i}", "title": f"Popular {i}", "url": f"https://p{i}.example/x", "claim": f"c{i}",
                 "node_ids": ["POPULAR"], "kind": "other", "strength": "direct", "quote": "q" * 20, "finding": "f",
                 "evidenceLevel": "direct_text_quote_found", "directExcerpt": "E" * 50,
                 "directRetrieval": {"sha256": "a" * 64, "quoteVerbatim": True},
                 "attribution": {"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"}}} for i in range(80)]
        lone = {"id": "LONE", "title": "The only source for a required topic", "url": "https://lone.example/x",
                "claim": "the one claim", "node_ids": ["RARE"], "kind": "other", "strength": "direct",
                "quote": "q" * 20, "finding": "f", "evidenceLevel": "direct_text", "directExcerpt": "E" * 50,
                "directRetrieval": {"sha256": "b" * 64, "quoteVerbatim": False}}
        research = {"sources": srcs + [lone]}
        required = ["POPULAR", "RARE"]
        for cap in (5, 25, 60):
            chosen, om = prompts.select_sources(research, cap=cap, required_nodes=required)
            ids = {s["id"] for s in chosen}
            self.assertIn("LONE", ids, f"cap={cap}: the sole support for a required topic must never be cut, "
                                       "even though 80 stronger sources exist for another topic")
            self.assertLessEqual(len(chosen), cap)
            self.assertEqual(om.get("topicsWithSupportNoneOfWhichIsShown") or [], [], f"cap={cap}: no topic is starved")
        # what was left out is reported, not hidden
        chosen, om = prompts.select_sources(research, cap=5, required_nodes=required)
        self.assertEqual(om["sourcesNotShown"], 76)
        self.assertEqual(om["ofThoseWithAQuotationFoundVerbatim"], 76, "and it says how many of them carried a quotation")
        prompt, _ = prompts.outline(BRIEF, PLAN, research)
        self.assertIn("<evidence_not_shown>", prompt, "the prompt says the list is a selection")
        self.assertIn("not everything Loom holds", prompt)

    def test_a_label_saying_what_loom_is_doing_does_not_survive_at_rest(self):
        """The acceptance course sat at waiting_approval still labelled "Proposing an outline", which reads on the
        progress screen as a request still running. What ran is kept in `calls`; `now` is only the present moment."""
        f, cid, rec = begin("stale-now")
        r = engine.runner("pipe", cid)
        saved = r.load()
        self.assertEqual(saved["status"], "waiting_approval")
        saved["now"] = {"stage": "outline", "unit": "outline", "label": "Proposing an outline",
                        "startedAt": "2026-09-30T09:15:20Z", "steps": []}
        calls_before = len(saved.get("calls") or [])
        r.save(saved)
        got = engine.read("pipe", cid)
        self.assertIsNone(got["now"], "nothing is being done, so nothing is labelled as being done")
        self.assertEqual(got["status"], "waiting_approval", "and the course is not disturbed")
        self.assertEqual(len(got.get("calls") or []), calls_before, "the record of what ran is kept")
        self.assertIsNone(engine.runner("pipe", cid).load()["now"], "and it is cleared on disk, not only in the copy")

    def test_retrieved_page_furniture_with_nothing_matched_supports_nothing(self):
        """The attribution review found about twenty records labelled direct_text whose text was only page
        navigation. A menu is not the page."""
        from loom_server import evidence
        nav = "\n".join(["Home", "About", "Docs", "Search", "Log in", "Next", "Previous", "Contents"] * 6)
        prose = "This sentence has a reasonable number of words in it. " * 40
        self.assertTrue(evidence.mostly_short_lines(nav))
        self.assertFalse(evidence.mostly_short_lines(prose))
        self.assertFalse(evidence.mostly_short_lines("Short.\nLines.\nBut.\nToo.\nFew."), "too little to judge")

        # nothing matched in furniture: flagged
        u = evidence.upgrade({"quote": "a quotation that is not on this page at all"}, {"ok": True, "text": nav})
        self.assertTrue(u["directRetrieval"]["textMostlyShortLines"])
        self.assertEqual(u["evidenceLevel"], "direct_text")

        # a page whose quotation WAS found is not flagged, even with a menu alongside it
        mixed = nav + "\n" + prose + "\nthe quoted sentence appears right here in the body."
        u2 = evidence.upgrade({"quote": "the quoted sentence appears right here in the body."}, {"ok": True, "text": mixed})
        self.assertEqual(u2["evidenceLevel"], "direct_text_quote_found")
        self.assertNotIn("textMostlyShortLines", u2["directRetrieval"], "a matched quotation shows the content was there")

    def test_a_topic_supported_only_by_page_furniture_is_not_counted_as_supported(self):
        from loom_server import evidence
        f, cid, rec = begin("nav-support")
        r = engine.runner("pipe", cid).load()
        node = r["stages"]["map"]["output"]["nodes"][0]
        s_ = dict(r["stages"]["research"]["output"]["sources"][0], id="SN", node_ids=[node["id"]], strength="direct")
        nav = "\n".join(["Home", "About", "Docs", "Search", "Log in"] * 8)
        s_ = evidence.upgrade(s_, {"ok": True, "text": nav, "sha256": "c" * 64, "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"})
        self.assertTrue(s_["directRetrieval"]["textMostlyShortLines"])
        r["stages"]["research"]["output"]["sources"] = [s_]
        for b in r["stages"]["research"]["batches"]:
            b.setdefault("output", {})["sources"] = [s_]
        r["stages"]["research"]["direct"] = {}
        r["stages"]["research"]["node_findings"] = []
        engine.runner("pipe", cid)._merge_research(r)
        cov = {c["node"]: c["status"] for c in r["stages"]["research"]["output"]["nodeCoverage"]}
        self.assertEqual(cov.get(node["id"]), "none_found", "a menu supports nothing, even though the page was retrieved")

    def test_a_relationship_is_read_from_the_document_and_only_when_it_can_be_quoted(self):
        """The acceptance course has not one lineage entry, so no relationship could ever be verified. They are read
        from the documents, and a relationship nobody can quote is not recorded at all."""
        f, cid = self._legacy("lineage-read", n=3, pages=2)
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        self.assertEqual(rs["lineageProgress"]["pages"], 2, "one reading per page")
        self.assertEqual(len(rs["lineageRead"]), 2)
        s_ = rs["output"]["sources"][0]
        self.assertTrue(s_.get("lineage"), "the relationship reached the source record")
        rel = s_["lineage"][0]
        self.assertEqual(rel["relation"], "corrected")
        self.assertEqual(rel["earlier_work"], "doi:10.0000/earlier", "the identifier is preferred when the text gives one")
        self.assertTrue(rel["supporting_words"], "with the words that show it")
        self.assertEqual(s_["lineageRead"]["originOfItsOwnSubject"], "names_an_earlier_origin")

    def test_a_relationship_with_nothing_to_quote_is_not_recorded(self):
        f, cid = self._legacy("lineage-unquoted", n=2, pages=1)
        plan_file("lineage-unquoted", variant={"lineage_unquoted": True})
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        got = rec["stages"]["research"]["lineageRead"]
        self.assertTrue(got, "the page was read")
        self.assertEqual(next(iter(got.values()))["relationships"], [], "but an unquotable relationship is dropped")
        self.assertFalse(rec["stages"]["research"]["output"]["sources"][0].get("lineage"))

    def test_a_page_that_states_no_relationship_records_none_and_says_the_origin_is_unknown(self):
        f, cid = self._legacy("lineage-none", n=2, pages=1)
        plan_file("lineage-none", variant={"lineage_none": True})
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        got = next(iter(rec["stages"]["research"]["lineageRead"].values()))
        self.assertEqual(got["relationships"], [], "most pages state none, and that is the right answer")
        self.assertEqual(got["originOfItsOwnSubject"], "unknown")

    def test_a_relationship_that_was_read_actually_reaches_the_graph(self):
        """Relationships were attached to the sources after the graph had already been built from them, so every
        edge was left out however many had been read: the acceptance course showed 7 relationships and 0 edges."""
        f, cid = self._legacy("lineage-graph", n=2, pages=1)
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        self.assertTrue(any(s.get("lineage") for s in rs["output"]["sources"]), "a relationship was read")
        lin = rs["output"]["lineage"]
        self.assertTrue(lin["edges"], "and it is in the graph, not only on the source record")
        e = lin["edges"][0]
        self.assertEqual(e["relation"], "corrected")
        # Counted once per relationship, not once per claim resting on the page it was read from. The earlier
        # form of this check counted the source records instead, which is what let 43 relationships read from 19
        # of the acceptance course's pages become 71 edges.
        read = {(x["relation"], x["earlier_work"], x["supporting_words"])
                for x in (rs["lineageRead"].get(next(iter(rs["lineageRead"]))) or {}).get("relationships") or []}
        self.assertTrue(read, "a relationship was read from the page")
        self.assertEqual(len(lin["edges"]), len(read), "every relationship read becomes one edge: none dropped, none doubled")
        self.assertEqual(lin["summary"]["descentEdges"], len(read), "correcting is a claim of descent and is counted")
        self.assertEqual(sorted(e["fromSources"]), sorted(x["id"] for x in rs["output"]["sources"] if x.get("lineage")),
                         "and every record that carries it is named on the edge, so nothing is lost by counting it once")

    def _long_page(self, relation_at=15000):
        """A document whose one statement of descent sits far past the opening, as real papers do."""
        filler = "This paragraph describes the ordinary contents of the document in plain prose. " * 400
        rel = ("Related work\n"
               "This specification corrects the earlier specification described in doi:10.0000/earlier, "
               "which reported the wrong bound for the same measurement.\n")
        head = "A table has rows and columns. " * 20
        body = head + filler
        return body[:relation_at] + rel + body[relation_at:]

    def test_a_relationship_stated_far_past_the_opening_is_put_in_front_of_the_reading(self):
        """The reading was shown 1200 opening characters and 500 around a quotation. The acceptance course's own
        documents run to a median of about twenty thousand, so a relationship stated anywhere else could not be
        found, and an empty result meant only that nobody had looked there."""
        from loom_server import evidence
        text = self._long_page()
        self.assertGreater(len(text), 20000)
        self.assertEqual(evidence.lineage_sections(text[:1100], head_chars=1200), [], "nothing lies beyond the opening")

        secs = evidence.lineage_sections(text, head_chars=1200)
        self.assertTrue(secs, "the document is longer than the opening and states a relationship elsewhere")
        joined = " ".join(x["text"] for x in secs)
        self.assertIn("corrects the earlier specification", joined, "the sentence that states descent is shown")
        self.assertIn("doi:10.0000/earlier", joined, "and the identifier that names the earlier work with it")
        self.assertTrue(all(x["why_it_was_chosen"] for x in secs), "each passage says which words led Loom to it")
        self.assertTrue(all(x["from"] >= 1200 for x in secs), "the opening is not shown twice")

        scope = evidence.lineage_scope(text, secs, head_chars=1200, excerpt_chars=500)
        narrow = evidence.lineage_scope(text, [], head_chars=1200, excerpt_chars=500)
        self.assertGreater(scope["inspectedChars"], narrow["inspectedChars"], "more of the document is inspected")
        self.assertLess(scope["inspectedShare"], 1.0, "and Loom does not pretend it read all of it")
        self.assertEqual(scope["documentChars"], len(text))

    def test_the_selection_stays_inside_its_budget_and_never_invents_a_reason_to_look(self):
        from loom_server import evidence
        plain = "This page explains how to open a file and read a line from it. " * 600
        self.assertEqual(evidence.lineage_sections(plain, head_chars=1200), [],
                         "a document that says nothing about earlier work yields no passages, rather than a random slice")
        dense = ("Related work\nIt extends the earlier study.\nSee also doi:10.1000/a and doi:10.1000/b [1] [2].\n"
                 "This corrects the earlier report.\n" * 200)
        secs = evidence.lineage_sections(dense, head_chars=1200)
        self.assertLessEqual(len(secs), 8, "a reference list cannot turn into an unbounded request")
        self.assertLessEqual(sum(len(x["text"]) for x in secs), 6000, "and the budget holds")
        self.assertEqual(secs, sorted(secs, key=lambda x: x["from"]), "passages are shown in document order")

    def test_the_passages_selected_from_deep_in_a_document_actually_reach_the_request(self):
        """Selecting a passage is worth nothing unless it is what the reading is shown."""
        from loom_server import evidence, prompts
        long_text = self._long_page()
        real_fetch, real_prompt = evidence.fetch_original, prompts.lineage_extraction
        seen = []

        def fake_fetch(url, *a, **k):
            return {"ok": True, "status": 200, "text": long_text, "sha256": "b" * 64, "requestedUrl": url,
                    "finalUrl": url, "textMethod": "plain_text", "bytes": len(long_text), "contentType": "text/plain",
                    "note": "", "attemptedAt": "2026-09-30T00:00:00Z", "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"}

        def capture(pages):
            seen.append(pages)
            return real_prompt(pages)

        evidence.fetch_original, prompts.lineage_extraction = fake_fetch, capture
        try:
            f, cid, rec = begin("lineage-deep-prompt")
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence"})
            rec = wait(cid)
        finally:
            evidence.fetch_original, prompts.lineage_extraction = real_fetch, real_prompt

        self.assertTrue(seen, "the reading was asked for")
        page = seen[0][0]
        extra = page.get("further_passages_from_the_same_document") or []
        self.assertTrue(extra, "passages from deeper in the document were included")
        shown = page["the_start_of_the_document"] + " " + (page.get("the_passage_around_a_quotation") or "") \
            + " " + " ".join(x["text"] for x in extra)
        self.assertIn("corrects the earlier specification", shown,
                      "the sentence stating descent is in the request, not merely selected somewhere")
        self.assertNotIn("inspected", page, "the scope is Loom's own record and is not put to the model as evidence")
        got = next(iter(rec["stages"]["research"]["lineageRead"].values()))
        self.assertGreater(got["inspected"]["inspectedChars"], 1700, "more than the old opening and quotation window")
        self.assertEqual(got["inspected"]["documentChars"], len(long_text))

    def test_who_made_a_document_is_looked_for_past_its_opening(self):
        """On the acceptance course's PMC article the DOI is at character 1216, the author list at 3679 and the
        corresponding author at 4627. The identity reading was shown the first 1200 characters, recorded "No author
        names and no DOI", and the attribution review then judged that source's identity only partly for exactly
        that reason — which is what stopped the one descent edge with both ends from being supported. Nothing was
        wrong with the document: nobody was shown the part of it that says who wrote it."""
        from loom_server import evidence
        head = "PMC Disclaimer. This article is available in PMC. " * 24
        middle = "The study describes a workshop and what the learners did. " * 40
        ident = ("doi: 10.21105/jose.00144\n"
                 "Author information: Zena Lapp 1, Kelly L Sovacool 1, Patrick D Schloss 2\n"
                 "1 Department of Computational Medicine & Bioinformatics\n"
                 "corresponding author. Issue date 2022.\n")
        text = head[:1200] + middle + ident + middle
        self.assertGreater(text.index("Patrick D Schloss"), 1200, "the authors are past the opening, as they were")

        secs = evidence.identity_sections(text, head_chars=1200)
        shown = " ".join(x["text"] for x in secs)
        self.assertIn("Patrick D Schloss", shown, "the author list is put in front of the reading")
        self.assertIn("10.21105/jose.00144", shown, "and the identifier with it")
        scope = evidence.identity_scope(text, secs, head_chars=1200, excerpt_chars=500)
        self.assertEqual(scope["scopeVersion"], evidence.IDENTITY_SCOPE_VERSION)
        self.assertEqual(scope["windows"]["sectionBudget"], 4000, "the scope reports the budget actually used")
        self.assertGreater(scope["inspectedChars"], 1700)

    def test_the_identity_and_lineage_cues_do_not_disturb_one_another(self):
        """Both selections run on the same server, and stages run in their own threads."""
        from loom_server import evidence
        text = ("Related work: this corrects the earlier report. " * 20) + ("Author information: Ada Ito. " * 20) + ("Body. " * 800)
        before = list(evidence._LINEAGE_CUES)
        i1 = evidence.identity_sections(text, head_chars=1200)
        l1 = evidence.lineage_sections(text, head_chars=1200)
        i2 = evidence.identity_sections(text, head_chars=1200)
        self.assertEqual(list(evidence._LINEAGE_CUES), before, "no selection rewrites the other's cues")
        self.assertEqual([x["from"] for x in i1], [x["from"] for x in i2], "and one run does not change the next")
        self.assertTrue(i1 and l1)

    def test_an_identity_read_on_a_narrower_scope_is_read_again(self):
        from loom_server import evidence
        f, cid = self._legacy("identity-scope-cache", n=2, pages=1)
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        wait(cid)
        r = engine.runner("pipe", cid).load()
        key = next(iter(r["stages"]["research"]["identity"]))
        self.assertEqual(r["stages"]["research"]["identity"][key]["inspected"]["scopeVersion"],
                         evidence.IDENTITY_SCOPE_VERSION, "what was inspected is recorded with the reading")
        r["stages"]["research"]["identity"][key]["inspected"]["scopeVersion"] = 0
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("read_identity", {"action": "read_identity"})
        rec = wait(cid)
        self.assertEqual(rec["stages"]["research"]["identityProgress"]["pages"], 1, "the page is read again")
        self.assertEqual(rec["stages"]["research"]["identity"][key]["inspected"]["scopeVersion"],
                         evidence.IDENTITY_SCOPE_VERSION)

    def test_a_named_earlier_work_is_fetched_so_the_relationship_has_another_end(self):
        """Every relationship in the acceptance course's graph had an unresolved far end. A chain with one end
        missing is not a discovery history, however many relationships were read."""
        from loom_server import evidence
        f, cid = self._legacy("endpoint-resolve", n=2, pages=1)
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        s0 = rs["output"]["sources"][0]
        sha = (s0.get("directRetrieval") or {}).get("sha256")
        rs["lineageRead"] = {pipeline.norm_url(s0["url"]): {
            "relationships": [{"relation": "extended", "earlier_work": "doi:10.1234/first",
                               "earlier_work_as_named": "doi:10.1234/first", "what_changed": "adds a case",
                               "supporting_words": "A table has rows and columns", "limits": ""}],
            "originOfItsOwnSubject": "names_an_earlier_origin", "note": "", "sha256": sha,
            "inspected": {"scopeVersion": 99}, "readAt": "2026-09-30T00:00:00Z"}}
        engine.runner("pipe", cid).save(r)
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        engine.runner("pipe", cid).save(r)
        edge = [e for e in r["stages"]["research"]["output"]["lineage"]["edges"] if e["relation"] == "extended"][0]
        self.assertIsNone(edge["to"], "the earlier work is named but nothing holds it")

        asked = []

        def fake_fetch(url, *a, **k):
            asked.append(url)
            body = "A first report. We introduce the method described here. " * 40
            return {"ok": True, "status": 200, "text": body, "sha256": "f" * 64, "requestedUrl": url, "finalUrl": url,
                    "textMethod": "plain_text", "bytes": len(body), "contentType": "text/plain", "note": "",
                    "attemptedAt": "2026-09-30T00:00:00Z", "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"}

        real = evidence.fetch_original
        evidence.fetch_original = fake_fetch
        try:
            engine.runner("pipe", cid).start("resolve_endpoints", {"action": "resolve_endpoints"})
            rec = wait(cid)
        finally:
            evidence.fetch_original = real

        self.assertEqual(asked, ["https://doi.org/10.1234/first"], "the registry that issued the identifier, once")
        self.assertIsNone(rec.get("pause"), "the stage finished rather than stopping on a problem")
        rs = rec["stages"]["research"]
        self.assertEqual(rs["endpointProgress"], dict(rs["endpointProgress"], works=1, done=1, fetched=1, stopped=False))
        got = rs["namedWorks"]["doi:10.1234/first"]
        self.assertTrue(got["ok"])
        self.assertEqual(got["namedBy"], sorted(x["id"] for x in rs["output"]["sources"] if x.get("lineage")),
                         "which records named it is kept")
        self.assertEqual(got["identityRead"]["sha256"], "f" * 64, "its identity was read from the bytes fetched")

        lin = rs["output"]["lineage"]
        edge = [e for e in lin["edges"] if e["relation"] == "extended"][0]
        self.assertTrue(edge["to"], "the relationship now has both ends")
        self.assertNotIn("the earlier work it names is not a work Loom holds, so the link has no other end", edge["why"])
        self.assertNotIn("NAMED:doi:10.1234/first", [x.get("id") for x in rs["output"]["sources"]],
                         "a work fetched as an endpoint is not a claim record and is not counted as a source")
        self.assertEqual(lin["works"][edge["to"]]["originStatus"], "unknown",
                         "fetching a work does not establish that it is an origin")
        w = lin["works"][edge["to"]]
        self.assertEqual(w["identifier"], "doi:10.1234/first",
                         "the work is the one the relationship named and Loom fetched")
        self.assertEqual(rs["output"]["namedWorks"][0]["identifierInTheDocument"], "doi:10.0000/fake",
                         "and where the document reports a different identifier that is shown, not silently taken")

    def test_an_earlier_work_named_only_as_an_idea_is_not_guessed_at(self):
        from loom_server import evidence
        f, cid = self._legacy("endpoint-idea", n=1, pages=1)
        r = engine.runner("pipe", cid).load()
        s0 = r["stages"]["research"]["output"]["sources"][0]
        r["stages"]["research"]["lineageRead"] = {pipeline.norm_url(s0["url"]): {
            "relationships": [{"relation": "extended", "earlier_work": "the computational notebook format",
                               "what_changed": "a", "supporting_words": "A table has rows and columns", "limits": ""}],
            "originOfItsOwnSubject": "names_an_earlier_origin", "note": "",
            "sha256": (s0.get("directRetrieval") or {}).get("sha256"),
            "inspected": {"scopeVersion": 99}, "readAt": "2026-09-30T00:00:00Z"}}
        engine.runner("pipe", cid).save(r)
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        engine.runner("pipe", cid).save(r)
        asked = []
        real = evidence.fetch_original
        evidence.fetch_original = lambda url, *a, **k: (asked.append(url), {"ok": False, "status": None, "text": "", "requestedUrl": url, "note": "no"})[1]
        try:
            engine.runner("pipe", cid).start("resolve_endpoints", {"action": "resolve_endpoints"})
            rec = wait(cid)
        finally:
            evidence.fetch_original = real
        self.assertEqual(asked, [], "nothing was fetched, because nothing was identified")
        self.assertEqual(rec["stages"]["research"]["namedWorks"], {})
        self.assertEqual(rec["stages"]["research"]["endpointProgress"]["works"], 0)
        edge = [e for e in rec["stages"]["research"]["output"]["lineage"]["edges"] if e["relation"] == "extended"][0]
        self.assertIsNone(edge["to"], "and the far end is still honestly missing")

    def test_a_reading_taken_on_a_narrower_scope_is_taken_again_rather_than_believed(self):
        """An empty result from a narrow scan must not stand in the way of a wider one."""
        from loom_server import evidence
        f, cid = self._legacy("lineage-scope-cache", n=2, pages=1)
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        got = rec["stages"]["research"]["lineageRead"]
        key = next(iter(got))
        self.assertEqual(got[key]["inspected"]["scopeVersion"], evidence.LINEAGE_SCOPE_VERSION,
                         "what was inspected, and under which rules, is recorded with the reading")

        r = engine.runner("pipe", cid).load()
        r["stages"]["research"]["lineageRead"][key]["inspected"]["scopeVersion"] = 0
        r["stages"]["research"]["lineageRead"][key]["relationships"] = []
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        again = rec["stages"]["research"]["lineageRead"][key]
        self.assertEqual(rec["stages"]["research"]["lineageProgress"]["pages"], 1, "the page is read again")
        self.assertEqual(rec["stages"]["research"]["lineageProgress"]["done"], 1, "and the reading finished")
        self.assertEqual(again["inspected"]["scopeVersion"], evidence.LINEAGE_SCOPE_VERSION)
        self.assertTrue(again["relationships"], "and the wider reading is what now stands")

    def test_an_empty_reading_says_it_was_not_found_in_what_was_inspected(self):
        f, cid = self._legacy("lineage-not-found-here", n=2, pages=1)
        plan_file("lineage-not-found-here", variant={"lineage_none": True})
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        got = next(iter(rec["stages"]["research"]["lineageRead"].values()))
        self.assertEqual(got["relationships"], [])
        self.assertTrue(got["notFoundHere"], "an empty result is a statement about the text that was read")
        self.assertLessEqual(got["inspected"]["inspectedShare"], 1.0)
        s_ = rec["stages"]["research"]["output"]["sources"][0]
        self.assertTrue(s_["lineageRead"]["notFoundHere"], "and it reaches the source record, not only the cache")
        self.assertIn("inspectedShare", s_["lineageRead"]["inspected"], "with how much of the document was inspected")

    def _texts(self, rec):
        """The retrieved text behind each source, which the reviewer is shown and the fingerprint now covers."""
        rs = rec["stages"]["research"]; direct = rs.get("direct") or {}
        return {x.get("id"): (direct.get(pipeline.claim_key(x)) or {}).get("text")
                for x in (rs.get("output") or {}).get("sources") or []}

    def test_an_attribution_yes_does_not_survive_a_relationship_attached_after_it(self):
        """The acceptance course carried twenty saved verdicts whose fingerprint no longer matched the record they
        described, three of them holding up supported graph edges. Attribution was checked before the relationships
        read from the documents were attached, and a relationship is part of what a verdict is judged against, so a
        yes given without one stayed a yes once one arrived."""
        from loom_server.engine import content_print, attribution_material
        f, cid = self._legacy("lineage-attribution-order", n=2, pages=1)
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        s0 = rs["output"]["sources"][0]
        self.assertFalse(s0.get("lineage"), "no relationship is on the record yet")
        # A genuine earlier yes, fingerprinted against the record exactly as it then stood.
        rs["attribution"] = {pipeline.claim_key(s0): {"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"},
                                                      "fingerprint": content_print(attribution_material(s0)), "at": "2026-09-30T00:00:00Z"}}
        engine.runner("pipe", cid).save(r)
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        got = r["stages"]["research"]["output"]["sources"][0]
        self.assertEqual((got.get("attribution") or {}).get("verdict"), "yes", "nothing changed, so the yes stands")

        # Now a relationship is read out of the document, which is new evidence the verdict never saw.
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        got = rec["stages"]["research"]["output"]["sources"][0]
        self.assertTrue(got.get("lineage"), "the relationship reached the record")
        av = got.get("attribution") or {}
        self.assertEqual(av.get("verdict"), "stale", "and the verdict made without it no longer applies")
        self.assertTrue(av.get("supersededFingerprint"), "the verdict it replaces is kept, not silently dropped")
        self.assertEqual(av["fingerprint"], content_print(attribution_material(got, self._texts(rec).get(got.get("id")))),
                         "the fingerprint describes the record as it now stands")
        self.assertEqual((got.get("originalSource") or {}).get("status"), "not_verified",
                         "and nothing may be called an original on a verdict that has gone stale")

    def test_each_source_is_checked_against_its_own_document_not_another_one(self):
        """The staleness check read a leftover loop variable, so every source was fingerprinted against the LAST
        source's retrieved text. On the real course that falsely staled 32 of 113 verdicts immediately after a fresh
        review — exactly the sources carrying a relationship, because the retrieved text reaches the fingerprint
        through the passage behind each claimed relationship. So each source here claims a relationship whose words
        are in ITS OWN document and in no other."""
        from loom_server.engine import content_print, attribution_material
        f, cid, rec = begin("own-text")
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        made = []
        for i in range(3):
            words = f"this document number {i} extends the earlier study of its own subject"
            s_ = dict(rs["output"]["sources"][0], id=f"S{i}", url=f"https://e{i}.example.org/doc",
                      claim=f"claim {i}",
                      lineage=[{"relation": "extended", "earlier_work": f"doi:10.1/{i}",
                                "supporting_words": words, "what_changed": "x", "limits": ""}])
            made.append(s_)
        rs["output"]["sources"] = made
        rs["direct"] = {pipeline.claim_key(x): {"ok": True, "sha256": "a" * 64,
                                                "text": f"Opening of document {n}. " + (f"this document number {n} extends the earlier study of its own subject. " * 3) + ("filler. " * 60)}
                        for n, x in enumerate(made)}
        for b in rs["batches"]:
            b.setdefault("output", {})["sources"] = made
        engine.runner("pipe", cid).save(r)

        # Merge once so the sources carry the ids and shape the engine actually works with, THEN record a verdict
        # against each one's own document, which is the real sequence a review goes through.
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        rs = r["stages"]["research"]
        merged = rs["output"]["sources"]
        texts = {x["id"]: (rs["direct"].get(pipeline.claim_key(x)) or {}).get("text") for x in merged}
        self.assertEqual(len(set(t for t in texts.values() if t)), 3, "the three sources really do have different text")
        self.assertTrue(all(x.get("lineage") for x in merged), "each one claims a relationship, so its text matters")
        rs["attribution"] = {pipeline.claim_key(x): {"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"},
                                                     "fingerprint": content_print(attribution_material(x, texts[x["id"]])),
                                                     "at": "2026-10-01T00:00:00Z"} for x in merged}
        engine.runner("pipe", cid).save(r)

        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        verdicts = [(x["id"], (x.get("attribution") or {}).get("verdict")) for x in r["stages"]["research"]["output"]["sources"]]
        self.assertTrue(all(v == "yes" for _, v in verdicts),
                        f"nothing changed, so no verdict may go stale: {verdicts}")

    def test_a_verdict_difference_is_not_called_the_model_when_the_question_changed(self):
        """Same evidence is not the same question. The judge rules and the answer schema are part of the request,
        and changing either can move a verdict without touching a single source — which is exactly how a comparison
        of two runs was once read as being about the model when the asking had changed."""
        f, cid, rec = begin("request-provenance")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        key = next(iter(rs["attributionHistory"]))
        hist = rs["attributionHistory"][key]
        # Pretend the earlier run was made under different judge rules, with the SAME evidence, and disagreed.
        hist[-1] = dict(hist[-1], verdict="no",
                        provenance=dict(hist[-1]["provenance"], requestFingerprint="a-different-request"))
        r = engine.runner("pipe", cid).load()
        r["stages"]["research"]["attributionHistory"][key] = hist
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        dis = rec["stages"]["research"]["attribution"][key]["disagreesWithEarlierRun"]
        self.assertTrue(dis["sameEvidence"], "the evidence really was identical")
        self.assertFalse(dis["sameWholeRequest"], "but the rest of the request was not")
        self.assertIn("NOT evidence about the model alone", dis["note"])
        ar = rec["stages"]["research"]["attributionReview"]
        self.assertIn(key, ar["disagreements"], "it is still recorded")
        self.assertNotIn(key, ar["disagreementsOnAnIdenticalRequest"],
                         "but it is not counted as a clean one, which is the number that could mislead")

    def test_everything_the_reviewer_is_shown_is_covered_by_the_fingerprint(self):
        """The prompt and the fingerprint were built separately and had drifted apart.

        title, directHead, directExcerpt, retrievedExcerpt and quoteCaseExact all reached the reviewer's request
        while being invisible to attribution_material, so a verdict could stay bound to an "unchanged" record
        although the request behind it had changed. That is exactly how a comparison of two runs was read as
        evidence about the model when the inputs had in fact differed. One representation now feeds both.
        """
        from loom_server import prompts
        from loom_server.engine import content_print, attribution_material
        base = {"id": "S1", "url": "https://e.org/a", "title": "A title", "claim": "a claim", "quote": "a quotation here",
                "authors": ["A"], "published": "2020", "version_or_edition": "1", "identifier": "doi:10.1/a",
                "role": "original_contribution", "evidenceLevel": "direct_text_quote_found", "lineage": [],
                "directHead": "the opening of the document", "directExcerpt": "around the quotation",
                "retrievedExcerpt": "a tool summary",
                "directRetrieval": {"sha256": "a" * 64, "quoteVerbatim": True, "quoteCaseExact": True}}
        before = content_print(attribution_material(base, "the retrieved text"))
        # Every one of these changes the request the reviewer sees, so every one must change the fingerprint.
        for field, value in (("title", "A different title"), ("directHead", "a different opening"),
                             ("directExcerpt", "a different passage"), ("retrievedExcerpt", "a different summary"),
                             ("claim", "a different claim"), ("authors", ["B"]), ("published", "2021"),
                             ("version_or_edition", "2"), ("identifier", "doi:10.1/b"), ("role", "secondary_aid"),
                             ("evidenceLevel", "direct_text"), ("quote", "another quotation entirely")):
            self.assertNotEqual(content_print(attribution_material(dict(base, **{field: value}), "the retrieved text")),
                                before, f"{field} changes the reviewer's request and must change the fingerprint")
        for key, value in (("quoteVerbatim", False), ("quoteCaseExact", False), ("sha256", "b" * 64)):
            changed = dict(base, directRetrieval=dict(base["directRetrieval"], **{key: value}))
            self.assertNotEqual(content_print(attribution_material(changed, "the retrieved text")), before,
                                f"directRetrieval.{key} is shown to the reviewer and must change the fingerprint")
        # The prompt is built from the same representation, so a field cannot be shown without being covered.
        shown = prompts.attribution_reviewer_input(base, "the retrieved text")
        covered = attribution_material(base, "the retrieved text")
        self.assertEqual(set(shown) - {"url"}, set(covered) - {"url"},
                         "the reviewer sees exactly the fields the fingerprint covers")
        self.assertEqual(shown["reviewerInputVersion"], prompts.REVIEWER_INPUT_VERSION)

    def test_the_words_that_show_a_relationship_are_put_in_front_of_the_reviewer(self):
        """The reviewer judged lineage_supported from a 1200-character opening and a 500-character window.

        On the acceptance course 40 of 60 relationship quotations sit outside those windows — the Carpentries
        acknowledgement behind S3's `extended` claim is at character 18378 — so the reviewer was being asked whether
        words support a claim without being shown the words, and kept answering 'partly'.
        """
        from loom_server import prompts
        words = "We thank The Carpentries organization for providing instructor training and workshop protocols"
        text = ("filler sentence that is of no interest here. " * 400) + words + (" and then the paper continues. " * 40)
        self.assertGreater(text.index(words), 1700, "the words sit well beyond the old opening-plus-excerpt windows")
        s_ = {"id": "S3", "url": "https://e.org/p", "directHead": text[:1200], "directExcerpt": "unrelated passage",
              "lineage": [{"relation": "extended", "earlier_work": "doi:10.12688/f1000research.3-62.v2",
                           "supporting_words": words}]}
        got = prompts.attribution_reviewer_input(s_, text)["the_passages_that_show_each_claimed_relationship"]
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["found_in_retrieved_text"])
        self.assertEqual(got[0]["character_offset_in_the_document"], text.index(words))
        self.assertIn(words, got[0]["passage"], "the reviewer is shown the words themselves")
        self.assertLess(len(got[0]["passage"]), 1000, "bounded, so one citing page cannot run away with the request")

    def test_a_relationship_whose_words_are_not_in_the_retrieved_text_says_so(self):
        from loom_server import prompts
        s_ = {"id": "S9", "url": "https://e.org/p",
              "lineage": [{"relation": "extended", "earlier_work": "something",
                           "supporting_words": "a sentence that appears nowhere in the retrieved document"}]}
        got = prompts.attribution_reviewer_input(s_, "the document says something else entirely" * 20)[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertFalse(got[0]["found_in_retrieved_text"])
        self.assertIsNone(got[0]["passage"])
        self.assertIn("NOT found", got[0]["note"], "the reviewer is told, rather than left to assume")

    def test_every_judgement_is_kept_and_a_disagreement_on_identical_input_is_recorded(self):
        """A verdict is never silently replaced, and the same input answered two ways is an unresolved conflict."""
        f, cid, rec = begin("attrib-history")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        hist = rs.get("attributionHistory") or {}
        self.assertTrue(hist, "every run is kept")
        key = next(iter(hist))
        n0 = len(hist[key])
        self.assertGreaterEqual(n0, 1, "at least this run is kept")
        first = hist[key][-1]
        for field in ("runId", "at", "verdict", "fingerprint", "provenance"):
            self.assertIn(field, first, field)
        prov = first["provenance"]
        for field in ("batchInputFingerprint", "requestFingerprint", "promptCharacters", "sourcesInRequest",
                      "reviewerInputVersion", "model", "build"):
            self.assertIn(field, prov, f"provenance records {field}")

        # A second run on unchanged evidence. The fake reviewer answers the same way, so there is no disagreement.
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        hist = rec["stages"]["research"]["attributionHistory"]
        self.assertEqual(len(hist[key]), n0 + 1, "the earlier judgement is kept, not overwritten")
        self.assertNotEqual(hist[key][-2]["runId"], hist[key][-1]["runId"], "each run is its own record")
        self.assertEqual(hist[key][-2]["fingerprint"], hist[key][-1]["fingerprint"], "identical input")
        self.assertNotIn("disagreesWithEarlierRun", rec["stages"]["research"]["attribution"][key],
                         "same answer on the same input is not a disagreement")

        # Now force the second answer to differ on the SAME input, which is the case that must be surfaced.
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], verdict="no")
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        cur = rec["stages"]["research"]["attribution"][key]
        self.assertIn("disagreesWithEarlierRun", cur, "the same input answered two ways is recorded")
        dis = cur["disagreesWithEarlierRun"]
        self.assertEqual(dis["earlierVerdict"], "no")
        self.assertIn("UNRESOLVED", dis["note"])
        self.assertTrue(dis["sameEvidence"])
        self.assertTrue(dis["sameWholeRequest"], "nothing but the answer changed here, so it is a clean comparison")
        self.assertIn(key, rec["stages"]["research"]["attributionReview"]["disagreements"])
        self.assertIn(key, rec["stages"]["research"]["attributionReview"]["disagreementsOnAnIdenticalRequest"])
        self.assertEqual(cur["verdict"], rec["stages"]["research"]["attributionHistory"][key][-1]["verdict"],
                         "nothing was voted on: the latest judgement stands and the conflict is shown beside it")

    def test_every_saved_attribution_fingerprint_describes_the_finished_record(self):
        """Whatever the stage order, no saved verdict may claim to describe a record it does not match."""
        from loom_server.engine import content_print, attribution_material
        f, cid = self._legacy("lineage-attribution-fresh", n=3, pages=2)
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        _t = self._texts(r)
        rs["attribution"] = {pipeline.claim_key(s_): {"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"},
                                                      "fingerprint": content_print(attribution_material(s_, _t.get(s_.get("id")))), "at": "2026-09-30T00:00:00Z"}
                             for s_ in rs["output"]["sources"]}
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        rec = wait(cid)
        srcs = rec["stages"]["research"]["output"]["sources"]
        texts = self._texts(rec)
        checked = 0
        for s_ in srcs:
            av = s_.get("attribution")
            if av and av.get("fingerprint"):
                checked += 1
                self.assertEqual(av["fingerprint"], content_print(attribution_material(s_, texts.get(s_.get("id")))),
                                 f"{s_.get('id')} carries a verdict fingerprinted against different evidence")
        self.assertEqual(checked, len(srcs), "every source was judged, so every one of them is checked")

    def test_a_relationship_read_from_one_version_of_a_page_stops_applying_when_the_bytes_change(self):
        f, cid = self._legacy("lineage-bytes", n=2, pages=1)
        engine.runner("pipe", cid).start("read_lineage", {"action": "read_lineage"})
        wait(cid)
        r = engine.runner("pipe", cid).load()
        self.assertTrue(r["stages"]["research"]["output"]["sources"][0].get("lineage"))
        for k in r["stages"]["research"]["direct"]:
            r["stages"]["research"]["direct"][k]["sha256"] = "d" * 64
        for s_ in r["stages"]["research"]["output"]["sources"]:
            s_.pop("lineage", None)
        engine.runner("pipe", cid)._merge_research(r)
        got = r["stages"]["research"]["output"]["sources"][0]
        self.assertFalse(got.get("lineage"), "read from different bytes, so it no longer applies")
        self.assertNotIn("lineageRead", got)

    def test_a_new_course_captures_identity_and_role_on_every_source(self):
        """The 113 legacy acceptance records have no identity keys at all, which is why every attribution was
        rejected. A course researched now must carry them through into the merged record."""
        from loom_server import prompts
        f, cid, rec = begin("identity-new")
        srcs = rec["stages"]["research"]["output"]["sources"]
        self.assertTrue(srcs)
        for s_ in srcs:
            for field in ("authors", "published", "version_or_edition", "identifier", "role"):
                self.assertIn(field, s_, f"{field} must be carried, not dropped")
            self.assertTrue(s_.get("authors"), "who made it is recorded")
            self.assertTrue(s_.get("published"), "when it was published is recorded")
            self.assertIn(s_.get("role"), prompts_roles(), s_.get("role"))
        # and the research request asks for them, so this is not the fixture's doing alone
        p, schema = prompts.research_nodes(BRIEF, {"nodes": []}, [], [], "nodes-1")
        self.assertIn("IDENTITY", p)
        self.assertIn("original_contribution", p)
        for field in ("authors", "published", "version_or_edition", "identifier", "role", "lineage"):
            self.assertIn(field, schema["properties"]["sources"]["items"]["required"], field)

    def test_every_source_is_covered_with_no_cap_one_fetch_per_page_and_a_resumable_count(self):
        """The first-60 cap left later entries permanently unretrieved. The active course has 113 entries."""
        from loom_server import evidence, pipeline
        f, cid, rec = begin("no-cap")
        r = engine.runner("pipe", cid).load()
        srcs = r["stages"]["research"]["output"]["sources"]
        # 150 claims over 3 pages: past the old cap, and most of them share a page
        made = [dict(srcs[0], id=f"S{i}", url=f"https://e{i % 3}.example.org/doc", claim=f"claim number {i}") for i in range(150)]
        r["stages"]["research"]["output"]["sources"] = made
        for b in r["stages"]["research"]["batches"]:
            b.setdefault("output", {})["sources"] = made
        r["stages"]["research"]["direct"] = {}  # start from nothing, so the count below is only these 150
        engine.runner("pipe", cid).save(r)
        fetched = []
        real = evidence.fetch_original
        evidence.fetch_original = lambda url, *a, **k: (fetched.append(url), {"ok": True, "status": 200, "text": "nothing in particular", "sha256": "d" * 64, "requestedUrl": url, "finalUrl": url, "textMethod": "plain_text", "bytes": 5, "contentType": "text/plain", "note": "", "attemptedAt": "2026-09-30T00:00:00Z", "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"})[1]
        try:
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence"})
            rec = wait(cid)
        finally:
            evidence.fetch_original = real
        prog = rec["stages"]["research"]["directProgress"]
        self.assertEqual(prog["total"], 150)
        self.assertEqual(prog["done"], 150, "no entry is left behind by a cap")
        self.assertEqual(len(rec["stages"]["research"]["direct"]), 150)  # every claim has a record
        self.assertEqual(len(fetched), 3, "one page is fetched once however many claims rest on it")
        self.assertEqual(prog["pagesFetched"], 3)

    def test_a_second_run_fetches_only_what_is_still_missing(self):
        from loom_server import evidence
        f, cid, rec = begin("resume-direct")
        # The pipeline already retrieved these while building the outline, which is the point of integrating it.
        # Clear the records so this test measures the second run against a known first run.
        r = engine.runner("pipe", cid).load()
        self.assertTrue(r["stages"]["research"]["direct"], "retrieval ran as part of the ordinary route to an outline")
        r["stages"]["research"]["direct"] = {}
        engine.runner("pipe", cid).save(r)
        calls = []
        real = evidence.fetch_original
        evidence.fetch_original = lambda url, *a, **k: (calls.append(url), {"ok": True, "status": 200, "text": "x", "sha256": "e" * 64, "requestedUrl": url, "finalUrl": url, "textMethod": "plain_text", "bytes": 1, "contentType": "text/plain", "note": "", "attemptedAt": "2026-09-30T00:00:00Z", "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"})[1]
        try:
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence"})
            wait(cid)
            first = len(calls)
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence"})
            rec = wait(cid)
        finally:
            evidence.fetch_original = real
        self.assertGreater(first, 0)
        self.assertEqual(len(calls), first, "work already saved is not repeated")
        self.assertEqual(rec["stages"]["research"]["directProgress"]["done"], rec["stages"]["research"]["directProgress"]["total"])

    def test_a_retry_tries_again_only_where_trying_again_could_help(self):
        from loom_server import evidence, pipeline
        f, cid, rec = begin("retry-direct")
        r = engine.runner("pipe", cid).load()
        srcs = r["stages"]["research"]["output"]["sources"]
        keys = [pipeline.claim_key(x) for x in srcs]
        r["stages"]["research"]["direct"] = {
            keys[0]: {"ok": False, "status": 503, "note": "The page did not open.", "requestedUrl": srcs[0]["url"]},
            keys[1]: {"ok": False, "status": None, "blocked": True, "note": "That address is not on the public internet, so it was not opened.", "requestedUrl": srcs[1]["url"]},
        }
        if len(keys) > 2:
            r["stages"]["research"]["direct"][keys[2]] = {"ok": True, "status": 200, "text": "kept", "sha256": "f" * 64, "requestedUrl": srcs[2]["url"], "textMethod": "plain_text", "note": ""}
        engine.runner("pipe", cid).save(r)
        prog_before = r["stages"]["research"]["direct"]
        self.assertTrue(engine._worth_retrying(prog_before[keys[0]]), "a 503 may not happen again")
        self.assertFalse(engine._worth_retrying(prog_before[keys[1]]), "a private address is not retried")
        tried = []
        real = evidence.fetch_original
        evidence.fetch_original = lambda url, *a, **k: (tried.append(url), {"ok": True, "status": 200, "text": "x", "sha256": "a" * 64, "requestedUrl": url, "finalUrl": url, "textMethod": "plain_text", "bytes": 1, "contentType": "text/plain", "note": "", "attemptedAt": "2026-09-30T00:00:00Z", "retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http"})[1]
        try:
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence", "retryFailed": True})
            rec = wait(cid)
        finally:
            evidence.fetch_original = real
        self.assertIn(srcs[0]["url"], tried, "the refusal that might pass is tried again")
        after = rec["stages"]["research"]["direct"]
        self.assertFalse(after[keys[1]]["ok"], "the blocked address is left as it was")
        self.assertIn(engine.norm_url(srcs[1]["url"]), rec["stages"]["research"]["directProgress"]["cannotRetrieve"])

    def test_a_writer_is_given_the_real_passage_beside_the_tool_summary_that_contradicts_it(self):
        """The defect was that writers saw only the tool's summary. A summary that says the opposite of the page
        must not be the only thing in the prompt."""
        from loom_server import prompts
        research_out = {"sources": [{
            "id": "S1", "title": "Monthly averages", "url": "https://example.org/doc", "claim": "The mean is +10 degrees",
            "kind": "dataset", "quote": "the monthly mean is +10 degrees", "finding": "Says the mean is minus ten.",
            "retrievedExcerpt": "This page reports that the monthly mean is MINUS ten degrees, a cooling trend.",
            "evidenceLevel": "direct_text_quote_found", "strength": "direct", "fetch": "retrieved",
            "directExcerpt": "Table 2. Across the period the monthly mean is +10 degrees, rising slightly.",
            "directRetrieval": {"retrievedAt": "2026-09-30T00:00:00Z", "method": "direct_http", "status": 200, "sha256": "c" * 64,
                                "textMethod": "html_tags_removed", "quoteVerbatim": True, "addressesOpened": ["93.184.216.34"],
                                "locator": {"charStart": 10, "charEnd": 60}},
            "authors": ["A Researcher"], "published": "2026-01-01", "version_or_edition": "v2", "identifier": "doi:10/x",
            "role": "original_contribution", "lineage": [{"relation": "extends", "earlier_work": "W1", "what_changed": "more years"}],
            "attribution": {"verdict": "yes"}, "originalSource": {"status": "verified", "because": []},
            "sourceReview": {"supports_claim": "yes"}}]}
        d = prompts.sources_digest(research_out)[0]
        self.assertIn("+10 degrees", d["the_original_text_loom_retrieved_itself"], "the page's own words reach the writer")
        self.assertIn("MINUS ten", d["a_summary_made_by_a_tool"], "the summary is still shown, and labelled as a summary")
        self.assertNotEqual(d["the_original_text_loom_retrieved_itself"], d["a_summary_made_by_a_tool"])
        self.assertTrue(d["quote_found_in_the_original_verbatim"])
        self.assertEqual(d["where_in_the_page"], {"from_character": 10, "to_character": 60})
        self.assertEqual(d["loom_retrieved_it_itself"]["checksum_sha256"], "c" * 64)
        self.assertEqual(d["who_made_it"]["version_or_edition"], "v2")
        self.assertEqual(d["lineage"][0]["relation"], "extends")
        self.assertEqual(d["attribution_review_verdict"], "yes")
        self.assertEqual(d["counts_as_an_original_source"], "verified")
        # and the prompt itself tells the writer which of the two decides
        prompt, _ = prompts.materials(BRIEF, PLAN, research_out, {"sessions": [{"title": "t", "outcome": "o", "topics": []}]}, 0)
        self.assertIn("the original decides", prompt)
        self.assertIn("Table 2. Across the period", prompt, "the real passage is in the prompt, not only the summary")

    def test_a_source_with_no_retrieval_says_so_rather_than_showing_an_empty_passage(self):
        from loom_server import prompts
        d = prompts.sources_digest({"sources": [{"id": "S9", "title": "t", "claim": "c", "retrievedExcerpt": "a summary only", "evidenceLevel": "tool_summary"}]})[0]
        self.assertNotIn("the_original_text_loom_retrieved_itself", d)
        self.assertNotIn("quote_found_in_the_original_verbatim", d)
        self.assertEqual(d["evidence_level"], "tool_summary")

    def test_an_attribution_verdict_stops_applying_when_the_evidence_it_judged_changes(self):
        from loom_server import evidence, pipeline
        s_ = {"id": "S1", "url": "https://example.org/d", "claim": "c", "quote": "a quotation of some length",
              "authors": ["A"], "published": "2026", "version_or_edition": "v1", "identifier": "doi:1", "role": "original_contribution",
              "lineage": [], "evidenceLevel": "direct_text_quote_found", "directRetrieval": {"sha256": "1" * 64, "quoteVerbatim": True}}
        before = engine.content_print(engine.attribution_material(s_))
        for field, value in [("version_or_edition", "v2"), ("quote", "a different quotation entirely"), ("authors", ["B"]), ("identifier", "doi:2")]:
            self.assertNotEqual(engine.content_print(engine.attribution_material(dict(s_, **{field: value}))), before, field)
        changed = dict(s_)
        changed["directRetrieval"] = {"sha256": "2" * 64, "quoteVerbatim": True}
        self.assertNotEqual(engine.content_print(engine.attribution_material(changed)), before, "different bytes are different evidence")
        self.assertEqual(evidence.original_status(s_, "stale")["status"], "not_verified")
        self.assertIn("has since changed", evidence.original_status(s_, "stale")["because"][0])

    def test_a_judgement_made_on_older_evidence_is_marked_stale_when_the_record_is_merged(self):
        from loom_server import pipeline
        f, cid, rec = begin("attrib-stale")
        r = engine.runner("pipe", cid).load()
        srcs = r["stages"]["research"]["output"]["sources"]
        k = pipeline.claim_key(srcs[0])
        r["stages"]["research"]["attribution"] = {k: {"verdict": "yes", "fingerprint": "not-the-current-one", "detail": {}, "at": "2026-09-01T00:00:00Z"}}
        engine.runner("pipe", cid)._merge_research(r)
        got = {x["id"]: x for x in r["stages"]["research"]["output"]["sources"]}[srcs[0]["id"]]
        self.assertEqual(got["attribution"]["verdict"], "stale")
        self.assertEqual(got["attribution"]["supersededFingerprint"], "not-the-current-one")
        self.assertEqual(got["originalSource"]["status"], "not_verified")

    def test_case_is_not_ignored_when_a_quotation_is_called_exact(self):
        """K is not k. A match found by ignoring case is reported, but never called an exact quotation."""
        from loom_server import evidence
        d = evidence.upgrade({"quote": "the value is 10 K"}, {"ok": True, "text": "Table: the value is 10 k here."})["directRetrieval"]
        self.assertTrue(d["quoteVerbatim"], "it is still found, so the passage can be pointed at")
        self.assertFalse(d["quoteCaseExact"], "but it is not letter for letter")
        d2 = evidence.upgrade({"quote": "the value is 10 K"}, {"ok": True, "text": "Table: the value is 10 K here."})["directRetrieval"]
        self.assertTrue(d2["quoteCaseExact"])

    @staticmethod
    def _pdf(pages_text):
        """A small standard-font PDF, written here, so the test does not depend on any outside file."""
        kids, body, offs = [], [], {}
        font_n = 1 + 2 * len(pages_text) + 3
        for i, txt in enumerate(pages_text):
            content = "BT /F1 12 Tf 72 720 Td (" + txt.replace("(", r"\(").replace(")", r"\)") + ") Tj ET"
            page_n, cont_n = 3 + i * 2, 4 + i * 2
            kids.append(page_n)
            body.append((page_n, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_n} 0 R >> >> /Contents {cont_n} 0 R >>".encode()))
            body.append((cont_n, f"<< /Length {len(content)} >>\nstream\n{content}\nendstream".encode()))
        body.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
        body.append((2, ("<< /Type /Pages /Count %d /Kids [%s] >>" % (len(kids), " ".join(f"{k} 0 R" for k in kids))).encode()))
        body.append((font_n, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
        body.sort()
        out = b"%PDF-1.4\n"
        for num, data in body:
            offs[num] = len(out)
            out += f"{num} 0 obj\n".encode() + data + b"\nendobj\n"
        x, mx = len(out), max(offs) + 1
        out += f"xref\n0 {mx}\n0000000000 65535 f \n".encode()
        for i in range(1, mx):
            out += f"{offs.get(i, 0):010d} 00000 n \n".encode()
        return out + f"trailer\n<< /Size {mx} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()

    def test_a_pdf_gives_up_its_text_with_the_page_a_passage_came_from(self):
        from loom_server import evidence
        got = evidence.pdf_text(self._pdf(["The monthly mean is +10 degrees Celsius and rising",
                                           "Table 2 shows ten more years of data from the same station"]))
        self.assertEqual((got["method"], got["pages"]), ("pdf_text_extracted", 2))
        self.assertIn("+10 degrees Celsius", got["text"])
        self.assertTrue(evidence.find_quote("The monthly mean is +10 degrees Celsius", got["text"]))
        self.assertIsNone(evidence.find_quote("The monthly mean is -10 degrees Celsius", got["text"]), "the sign still decides")
        u = evidence.upgrade({"quote": "Table 2 shows ten more years of data"},
                             {"ok": True, "text": got["text"], "pageOffsets": got["pageOffsets"]})
        self.assertEqual(u["directRetrieval"]["locator"]["page"], 2, "a locator in a PDF says which page")
        self.assertEqual(u["evidenceLevel"], "direct_text_quote_found")

    @staticmethod
    def _pdf_obj(body, kids, count=1):
        out, offs = b"%PDF-1.4\n", {}
        full = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
                (2, ("<< /Type /Pages /Count %d /Kids [%s] >>" % (count, " ".join(f"{k} 0 R" for k in kids))).encode())] + body
        for n, d in sorted(full):
            offs[n] = len(out)
            out += f"{n} 0 obj\n".encode() + d + b"\nendobj\n"
        x, mx = len(out), max(offs) + 1
        out += f"xref\n0 {mx}\n0000000000 65535 f \n".encode()
        for i in range(1, mx):
            out += f"{offs.get(i, 0):010d} 00000 n \n".encode()
        return out + f"trailer\n<< /Size {mx} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()

    @staticmethod
    def _pdf_stream(n, content, extra=b""):
        return (n, (b"<< /Length %d %s >>\nstream\n" % (len(content), extra)) + content + b"\nendstream")

    HELV = (9, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    PAGE = b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 9 0 R >> >> /Contents %s >>"

    def test_a_page_built_from_several_streams_is_one_page_not_several(self):
        """Codex reproduced pages=2 for a single /Page with /Contents [4 0 R 5 0 R]. A content stream is not a page,
        and a page locator taken from stream order is invented."""
        from loom_server import evidence
        pdf = self._pdf_obj([(3, self.PAGE % b"[4 0 R 5 0 R]"),
                             self._pdf_stream(4, b"BT /F1 12 Tf (First stream on page one) Tj ET"),
                             self._pdf_stream(5, b"BT /F1 12 Tf (Second stream same page) Tj ET"), self.HELV], [3])
        got = evidence.pdf_text(pdf)
        self.assertEqual(got["pages"], 1, "one /Page is one page")
        self.assertEqual(got["pageOffsets"], [{"page": 1, "from": 0}])
        self.assertIn("First stream", got["text"])
        self.assertIn("Second stream", got["text"], "both streams of that page are its text")

    def test_a_locator_names_the_page_the_passage_is_really_on(self):
        from loom_server import evidence
        pdf = self._pdf_obj([(3, self.PAGE % b"4 0 R"), (5, self.PAGE % b"6 0 R"),
                             self._pdf_stream(4, b"BT /F1 12 Tf (Page one says alpha beta gamma) Tj ET"),
                             self._pdf_stream(6, b"BT /F1 12 Tf (Page two says delta epsilon zeta) Tj ET"), self.HELV], [3, 5], count=2)
        got = evidence.pdf_text(pdf)
        self.assertEqual(got["pages"], 2)
        u = evidence.upgrade({"quote": "Page two says delta epsilon zeta"},
                             {"ok": True, "text": got["text"], "pageOffsets": got["pageOffsets"]})
        self.assertEqual(u["directRetrieval"]["locator"]["page"], 2)

    def test_a_stream_no_page_refers_to_is_not_text_on_any_page(self):
        from loom_server import evidence
        pdf = self._pdf_obj([(3, self.PAGE % b"4 0 R"),
                             self._pdf_stream(4, b"BT /F1 12 Tf (The only real page text here) Tj ET"),
                             self._pdf_stream(7, b"BT /F1 12 Tf (ORPHAN STREAM NOBODY REFERS TO) Tj ET"), self.HELV], [3])
        got = evidence.pdf_text(pdf)
        self.assertEqual(got["pages"], 1)
        self.assertNotIn("ORPHAN", got["text"])

    def test_a_string_that_is_never_drawn_is_not_text_on_the_page(self):
        from loom_server import evidence
        pdf = self._pdf_obj([(3, self.PAGE % b"4 0 R"),
                             self._pdf_stream(4, b"(NEVER SHOWN STRING) BT /F1 12 Tf (this is the shown text here) Tj ET"), self.HELV], [3])
        got = evidence.pdf_text(pdf)
        self.assertNotIn("NEVER SHOWN", got["text"], "only the text-showing operators put text on a page")
        self.assertIn("shown text", got["text"])

    def test_a_font_loom_cannot_map_is_reported_unsupported_rather_than_guessed(self):
        from loom_server import evidence
        for font, word in [(b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H >>", "composite"),
                           (b"<< /Type /Font /Subtype /Type1 /BaseFont /X /Encoding << /Differences [1 /a] >> >>", "custom character mapping")]:
            pdf = self._pdf_obj([(3, self.PAGE % b"4 0 R"),
                                 self._pdf_stream(4, b"BT /F1 12 Tf (some text drawn with it) Tj ET"), (9, font)], [3])
            got = evidence.pdf_text(pdf)
            self.assertEqual(got["method"], "pdf_unsupported", font)
            self.assertEqual((got["text"], got["pages"]), ("", 0), "no text and no page count are kept")
            self.assertIn(word, got["note"])

    def test_a_stream_that_expands_too_far_is_refused_before_it_is_held(self):
        """Bounded rejection with a small compressed fixture, not a stress run."""
        from loom_server import evidence
        import zlib
        bomb = zlib.compress(b"A" * (40 * 1024 * 1024))
        self.assertLess(len(bomb), 200 * 1024, "the fixture itself is small")
        pdf = self._pdf_obj([(3, self.PAGE % b"4 0 R"),
                             self._pdf_stream(4, bomb, extra=b"/Filter /FlateDecode"), self.HELV], [3])
        got = evidence.pdf_text(pdf)
        self.assertEqual(got["method"], "pdf_unsupported")
        self.assertIn("expands beyond", got["note"])

    def test_a_flate_compressed_page_is_read_and_another_filter_is_refused(self):
        from loom_server import evidence
        import zlib
        good = zlib.compress(b"BT /F1 12 Tf (compressed page text reads fine) Tj ET")
        pdf = self._pdf_obj([(3, self.PAGE % b"4 0 R"), self._pdf_stream(4, good, extra=b"/Filter /FlateDecode"), self.HELV], [3])
        self.assertIn("compressed page text", evidence.pdf_text(pdf)["text"])
        odd = self._pdf_obj([(3, self.PAGE % b"4 0 R"),
                             self._pdf_stream(4, b"whatever", extra=b"/Filter /LZWDecode"), self.HELV], [3])
        got = evidence.pdf_text(odd)
        self.assertEqual(got["method"], "pdf_unsupported")
        self.assertIn("LZWDecode", got["note"])

    def test_a_page_tree_held_in_a_compressed_object_stream_is_still_found(self):
        """A PDF written to version 1.5 or later usually keeps its catalogue and page tree inside an /ObjStm."""
        from loom_server import evidence
        import zlib
        inner = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
                 (2, b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>"),
                 (3, self.PAGE % b"4 0 R"),
                 (9, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")]
        bodies, offs, at = [], [], 0
        for n, b in inner:
            offs.append(f"{n} {at}")
            bodies.append(b)
            at += len(b) + 1
        head = (" ".join(offs) + " ").encode()
        payload = head + b" ".join(bodies)
        comp = zlib.compress(payload)
        objstm = (10, (b"<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode /Length %d >>\nstream\n" % (len(inner), len(head), len(comp))) + comp + b"\nendstream")
        out = b"%PDF-1.5\n"
        pos = {}
        for n, d in [objstm, self._pdf_stream(4, b"BT /F1 12 Tf (text from an object stream pdf) Tj ET")]:
            pos[n] = len(out)
            out += f"{n} 0 obj\n".encode() + d + b"\nendobj\n"
        out += b"/Root 1 0 R\n%%EOF\n"
        got = evidence.pdf_text(out)
        self.assertEqual(got["pages"], 1, "the page tree inside the object stream was found")
        self.assertIn("object stream pdf", got["text"])

    def test_a_pdf_whose_page_tree_cannot_be_read_is_unsupported_not_guessed(self):
        from loom_server import evidence
        for bad in [b"%PDF-1.4\nnot really a pdf\n%%EOF", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"]:
            got = evidence.pdf_text(bad)
            self.assertEqual(got["method"], "pdf_unsupported")
            self.assertEqual(got["pages"], 0, "no page count is invented")

    def test_a_pdf_whose_text_cannot_be_read_is_reported_and_never_treated_as_checked(self):
        """A scanned page, or fonts this extractor has no map for, must not look like a verified passage."""
        from loom_server import evidence
        scanned = b"%PDF-1.4\n1 0 obj\n<< /Type /XObject /Subtype /Image /Filter /DCTDecode /Length 4 >>\nstream\n\xff\xd8\xff\xd9\nendstream\nendobj\n%%EOF\n"
        got = evidence.pdf_text(scanned)
        self.assertEqual(got["method"], "pdf_unsupported", "no page tree, so Loom does not claim to know why")
        self.assertEqual(got["text"], "")
        self.assertEqual(got["pages"], 0, "no page count is invented")
        u = evidence.upgrade({"quote": "anything at all in here", "evidenceLevel": "tool_summary"}, {"ok": True, "text": got["text"]})
        self.assertEqual(u["evidenceLevel"], "tool_summary", "with no text there is nothing to raise it above the summary")
        self.assertFalse(u["directRetrieval"]["quoteVerbatim"])
        self.assertEqual(evidence.original_status(u, "yes")["status"], "not_verified")

    def test_a_pdf_arrives_through_retrieval_with_its_checksum_and_its_extracted_text(self):
        from loom_server import evidence
        import hashlib
        data = self._pdf(["A published statement of some length for testing"])
        Page.PDF_BYTES = data
        try:
            r = evidence.fetch_original(self.url("/pdf-real"), allow_local=True)
        finally:
            Page.PDF_BYTES = None
        self.assertTrue(r["ok"])
        self.assertEqual(r["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(r["textMethod"], "pdf_text_extracted")
        self.assertIn("A published statement", r["text"])
        self.assertEqual(r["pdfPages"], 1)

    def test_a_result_belongs_to_the_exact_file_it_was_run_on(self):
        from loom_server import pipeline
        good = {"name": "chart.py", "kind": "code", "run": "run", "content": "print('ok')"}
        ran = {"name": "chart.py", "kind": "code", "check": "run", "assetPrint": pipeline.asset_print(good), "state": "ran", "level": "executed", "output": "ok"}
        self.assertEqual(pipeline.checks_for([good], [ran]), [ran])
        edited = dict(good, content="print('ok')  # changed")
        self.assertNotEqual(pipeline.asset_print(edited), pipeline.asset_print(good))
        out = pipeline.checks_for([edited], [ran])
        self.assertEqual(out[0]["state"], "stale")
        self.assertEqual(out[0]["level"], "not_run", "a changed program never inherits an earlier pass")
        self.assertEqual(pipeline.checks_for([{"name": "other.py", "content": "x"}], [ran]), [], "a file that is gone leaves no result")

    def test_running_an_asset_records_which_file_it_ran(self):
        from loom_server import pipeline
        a = {"name": "t.py", "kind": "code", "run": "run", "language": "python", "content": "print(2 + 2)"}
        r = pipeline.run_assets([a], [])[0]
        self.assertEqual(r["assetPrint"], pipeline.asset_print(a))

    def test_the_start_of_a_retrieved_document_is_kept_so_identity_can_be_judged(self):
        """A document says who made it, when, and what it updates at its start. Without that a reviewer asked to
        judge identity or descent can only say it cannot tell, however good the quotation is."""
        from loom_server import evidence, prompts
        text = "Request for Comments: 5746\nUpdates: 5246\nFebruary 2010\n\n" + ("filler. " * 200) + "the quoted sentence appears here"
        u = evidence.upgrade({"id": "S1", "quote": "the quoted sentence appears here", "role": "primary_extension"},
                             {"ok": True, "text": text})
        self.assertIn("Updates: 5246", u["directHead"], "the opening is kept")
        self.assertNotIn("Updates: 5246", u["directExcerpt"], "the excerpt is only the passage around the quotation")
        prompt, _ = prompts.attribution_review({"topics": ["x"], "outcome": "y"}, {"nodes": []}, [u])
        self.assertIn("Updates: 5246", prompt, "so the reviewer can see what the document says it updates")
        self.assertIn("the_start_of_the_document_loom_retrieved", prompt)

    def test_every_delivery_mode_and_a_short_talk_reach_the_expanded_pipeline_s_writers_too(self):
        """The expanded pipeline builds its session request on top of the same base, so each mode's rule must
        still be in it, along with the short-talk rule. Prompt text only: it says nothing about quality."""
        from loom_server import prompts
        outline_out = {"sessions": [{"title": "t", "outcome": "o", "topics": [], "teaches": [], "practises": [],
                                     "independent_work": {"minutes": 0, "tasks": []}}], "course_outcome": "c", "final_evidence": "f"}
        for key, phrase in [("live", "Delivery is ONLINE AND LIVE"), ("room", "Delivery is IN A ROOM"),
                            ("hybrid", "Delivery is ROOM AND ONLINE TOGETHER"), ("self", "Delivery is SELF-PACED"),
                            ("blended", "Delivery is BLENDED")]:
            brief = dict(BRIEF, deliveryKey=key)
            p, _ = prompts.materials2(brief, PLAN, {"nodes": []}, None, outline_out, 0, None, [], [], {"minor": 0, "major": 0, "note": ""})
            self.assertIn(phrase, p, f"the {key} rule reaches the expanded pipeline's session request")
        short = dict(BRIEF, formatKey="talk")
        p, _ = prompts.materials2(short, dict(PLAN, minutes=[20]), {"nodes": []}, None, outline_out, 0, None, [], [], {"minor": 0, "major": 0, "note": ""})
        self.assertIn("This is SHORT", p, "a short talk is not written as a small workshop")

    def test_a_quote_is_found_only_verbatim_and_never_by_a_paraphrase_and_a_locator_is_given(self):
        from loom_server import evidence
        text = "A table has rows and columns.\nEach row is one record and each column one measurement."
        hit = evidence.find_quote("Each row is one record and each column one measurement", text)
        self.assertIsNotNone(hit)
        self.assertEqual(text[hit["charStart"]:hit["charEnd"]].lower().split()[0], "each")
        # Case and spacing are the only things normalised, so a line break inside the quotation is still a match.
        self.assertIsNotNone(evidence.find_quote("rows and columns.  Each row is one record", text))
        self.assertIsNone(evidence.find_quote("every row holds a single record of one thing measured", text), "a paraphrase is not a quotation")
        # Punctuation the source does not have makes it not verbatim. Loom fails closed: the same leniency that
        # accepted an added comma also made "10,500" match "10500" and "+10" match "-10".
        self.assertIsNone(evidence.find_quote("each row is one record, and each column one measurement", text))
        self.assertIsNone(evidence.find_quote("short", text))

    def test_a_quotation_that_changes_a_sign_a_decimal_an_operator_or_a_separator_is_not_a_match(self):
        """Codex reproduced '+10' matching '-10'. A label that says verbatim must never rest on that."""
        from loom_server import evidence
        for quote, text in [("The measured value is +10 degrees.", "The measured value is -10 degrees."),
                            ("a rise of 1.5 degrees Celsius", "a rise of 15 degrees Celsius"),
                            ("x > 3 is required here", "x < 3 is required here"),
                            ("the value is 10,500 units", "the value is 10500 units"),
                            ("the ratio is 3/4 of the whole", "the ratio is 3-4 of the whole")]:
            self.assertIsNone(evidence.find_quote(quote, text), f"{quote!r} must not match {text!r}")
            self.assertIsNotNone(evidence.find_quote(quote, f"before. {quote} after."), "the true passage must still be found")

    def test_only_case_spacing_and_typographic_variants_are_normalised(self):
        from loom_server import evidence
        self.assertIsNotNone(evidence.find_quote("a value of -10 degrees", "a value of \u221210 degrees"))  # minus sign
        self.assertIsNotNone(evidence.find_quote('the "clean" dataset is used', "the \u201cclean\u201d dataset is used"))
        self.assertIsNotNone(evidence.find_quote("THE MEASURED VALUE IS +10", "the measured  value\nis +10"))
        self.assertIsNotNone(evidence.find_quote("a soft hyphen inside a word", "a soft hy\u00adphen inside a word"))

    def test_a_summary_is_never_original_and_three_separate_conditions_are_all_needed(self):
        from loom_server import evidence
        s = {"role": "original_contribution", "evidenceLevel": "tool_summary"}
        self.assertEqual(evidence.original_status(s, "yes")["status"], "not_verified")
        self.assertIn("only a tool-made summary", evidence.original_status(s, "yes")["because"][0])
        s = {"role": "secondary_aid", "evidenceLevel": "direct_text_quote_found"}
        self.assertEqual(evidence.original_status(s, "yes")["status"], "not_verified")
        s = {"role": "original_contribution", "evidenceLevel": "direct_text_quote_found"}
        self.assertEqual(evidence.original_status(s, None)["status"], "not_verified")
        self.assertEqual(evidence.original_status(s, "yes"), {"status": "verified", "because": []})

    def test_verifying_a_saved_run_upgrades_only_what_loom_itself_retrieved_and_keeps_the_summary_labelled(self):
        f, cid, rec = begin("verify-evidence")
        r = engine.runner("pipe", cid).load()
        for s in r["stages"]["research"]["output"]["sources"]:
            self.assertEqual(s.get("evidenceLevel"), "tool_summary")
            self.assertEqual(s["originalSource"]["status"], "not_verified") if "originalSource" in s else None
        orig = engine.ALLOW_LOCAL_FETCH
        engine.ALLOW_LOCAL_FETCH = True
        try:
            # point one source at the local page whose text contains its quote
            r["stages"]["research"]["output"]["sources"][1]["url"] = self.url("/page")
            for b in r["stages"]["research"]["batches"]:
                for s in b.get("output", {}).get("sources", []):
                    if s["url"].endswith("nodes-1"):
                        s["url"] = self.url("/page")
            engine.runner("pipe", cid).save(r)
            engine.runner("pipe", cid).start("verify_evidence", {"action": "verify_evidence"})
            rec = wait(cid)
        finally:
            engine.ALLOW_LOCAL_FETCH = orig
        srcs = {s["url"]: s for s in rec["stages"]["research"]["output"]["sources"]}
        mine = srcs[self.url("/page")]
        self.assertEqual(mine["evidenceLevel"], "direct_text_quote_found")
        self.assertTrue(mine["directRetrieval"]["quoteVerbatim"])
        self.assertTrue(mine["directRetrieval"]["sha256"])
        self.assertEqual(mine["originalSource"]["status"], "not_verified", "no attribution review has judged it yet")
        others = [s for u, s in srcs.items() if u != self.url("/page")]
        self.assertTrue(others and all(s["evidenceLevel"] in ("tool_summary", "none", "direct_text") for s in others), "a page Loom could not retrieve keeps its summary label")

    def test_a_separate_attribution_review_can_complete_the_three_conditions_and_can_refuse_them(self):
        f, cid, rec = begin("attribution", attr_no=["S2"])
        orig = engine.ALLOW_LOCAL_FETCH
        engine.ALLOW_LOCAL_FETCH = True
        r = engine.runner("pipe", cid).load()
        try:
            for b in r["stages"]["research"]["batches"]:
                for s in b.get("output", {}).get("sources", []):
                    s["url"] = self.url("/page")
            engine.runner("pipe", cid)._merge_research(r)
            engine.runner("pipe", cid).save(r)
            for action in ("verify_evidence", "attribution_review"):
                engine.runner("pipe", cid).start(action, {"action": action})
                rec = wait(cid)
        finally:
            engine.ALLOW_LOCAL_FETCH = orig
        by_id = {s["id"]: s for s in rec["stages"]["research"]["output"]["sources"]}
        self.assertEqual(by_id["S1"]["originalSource"]["status"], "verified")
        self.assertEqual(by_id["S2"]["originalSource"]["status"], "not_verified")
        self.assertTrue(any("attribution review said" in x for x in by_id["S2"]["originalSource"]["because"]))
        self.assertEqual(rec["stages"]["research"]["attributionReview"]["output"]["verdict"], "concerns")


class LegacyVerdicts(unittest.TestCase):
    def test_a_verdict_kept_by_address_alone_applies_only_where_one_claim_uses_the_page(self):
        f, cid, rec = begin("legacy-verdicts")
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        # two claims on one page, and one claim on another; an old build stored a single verdict per address
        first = rs["batches"][0]["output"]["sources"][0]
        twin = dict(first, claim="A different claim on the same page")
        rs["batches"][1]["output"]["sources"].append(twin)
        rs["verdicts"] = {engine.norm_url(first["url"]): {"supports_claim": "no", "reason": "old"}}
        other = rs["batches"][1]["output"]["sources"][0]
        rs["verdicts"][engine.norm_url(other["url"])] = {"supports_claim": "yes", "reason": "old"}
        engine.runner("pipe", cid)._merge_research(r)
        by_claim = {s["claim"]: s for s in r["stages"]["research"]["output"]["sources"]}
        self.assertEqual(by_claim[other["claim"]]["sourceReview"]["supports_claim"], "yes")
        self.assertEqual(by_claim[first["claim"]]["sourceReview"]["supports_claim"], "not_judged", "two claims on one page: the old verdict cannot be assigned to either")
        self.assertEqual(by_claim[twin["claim"]]["sourceReview"]["supports_claim"], "not_judged")


class DisagreementIsDetectedQuestionByQuestion(unittest.TestCase):
    """Comparing two runs on the aggregate verdict alone hid the disagreements that decide the lineage graph.

    The aggregate is "yes" only when identity, role and descent are all affirmative, so it sits still at "concerns"
    while a single relationship underneath it flips from yes to no — and that flip is exactly what decides whether
    a link stands. These run the real engine against the fake CLI in isolated temporary storage.
    """

    def _run(self, cid):
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        return wait(cid)

    def _claims_a_relationship(self, cid):
        """Give every source one claimed relationship, so there is a per-relationship judgement to compare."""
        rel = [{"relation": "corrected", "earlier_work": "The earlier specification",
                "earlier_work_identifier": "doi:10.0000/earlier", "what_changed": "fixes a flaw",
                "supporting_words": "A table has rows and columns", "limits": ""}]
        r = engine.runner("pipe", cid).load()
        made = [dict(x, lineage=rel) for x in r["stages"]["research"]["output"]["sources"]]
        r["stages"]["research"]["output"]["sources"] = made
        for b in r["stages"]["research"]["batches"]:
            b.setdefault("output", {})["sources"] = made
        engine.runner("pipe", cid).save(r)

    def _key(self, rec):
        return next(iter(rec["stages"]["research"]["attributionHistory"]))

    def test_a_relationship_flip_is_caught_though_the_overall_verdict_never_moves(self):
        f, cid, rec = begin("attrib-per-relationship", attr_rel="yes")
        self._claims_a_relationship(cid)
        rec = self._run(cid)
        key = self._key(rec)
        before = rec["stages"]["research"]["attribution"][key]
        self.assertTrue(before["detail"].get("relationships"), "this fixture judges relationships separately")
        self.assertNotIn("unresolvedDisagreements", before, "one run cannot disagree with itself")

        # The SAME evidence, the same request, the same overall verdict — and the opposite answer about the one
        # relationship. Nothing above it moves, which is why the aggregate comparison never saw this.
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        flipped = dict(h[-1]["detail"], relationships=[dict(x, supported="no") for x in h[-1]["detail"]["relationships"]])
        h[-1] = dict(h[-1], detail=flipped)
        engine.runner("pipe", cid).save(r)
        rec = self._run(cid)

        cur = rec["stages"]["research"]["attribution"][key]
        self.assertEqual(cur["verdict"], before["verdict"], "the overall verdict really did not move")
        live = cur.get("unresolvedDisagreements") or []
        self.assertTrue(live, "a relationship answered two ways on the same evidence is a disagreement")
        d = live[0]
        self.assertEqual(d["aspect"], "relationship")
        self.assertEqual((d["earlier"], d["later"]), ("no", "yes"))
        self.assertTrue(d["sameEvidence"])
        self.assertTrue(d["sameWholeRequest"], "nothing but the answer changed")
        self.assertIn("UNRESOLVED", d["note"])

    def test_identity_and_role_are_compared_as_their_own_questions(self):
        f, cid, rec = begin("attrib-identity-aspect")
        rec = self._run(cid)
        key = self._key(rec)
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no", role_correct="no"))
        engine.runner("pipe", cid).save(r)
        rec = self._run(cid)
        got = {d["aspect"] for d in rec["stages"]["research"]["attribution"][key].get("unresolvedDisagreements") or []}
        self.assertIn("identity", got)
        self.assertIn("role", got)

    def test_a_question_one_run_left_blank_is_not_turned_into_a_disagreement(self):
        """An omission is an omission. Reading it as a contradiction would be the same mistake, in reverse, as
        reading it as a confirmation: both invent an answer nobody gave."""
        f, cid, rec = begin("attrib-omitted")
        rec = self._run(cid)
        key = self._key(rec)
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail={k: v for k, v in h[-1]["detail"].items() if k != "role_correct"})
        engine.runner("pipe", cid).save(r)
        rec = self._run(cid)
        got = {d["aspect"] for d in rec["stages"]["research"]["attribution"][key].get("unresolvedDisagreements") or []}
        self.assertNotIn("role", got, "nobody gave two answers about the role")

    def test_a_contradiction_does_not_expire_by_being_repeated(self):
        """Answer yes, then no, then no again: the last two agree, so comparing only against the run before would
        show nothing wrong by the third, while the first two still contradict each other on the same evidence."""
        f, cid, rec = begin("attrib-carry-forward")
        rec = self._run(cid)
        key = self._key(rec)
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no"))
        engine.runner("pipe", cid).save(r)
        rec = self._run(cid)
        self.assertTrue(rec["stages"]["research"]["attribution"][key].get("unresolvedDisagreements"), "raised here")

        # A third run that agrees with the second. The question between runs one and two is still open.
        rec = self._run(cid)
        live = rec["stages"]["research"]["attribution"][key].get("unresolvedDisagreements") or []
        self.assertTrue(live, "an unsettled question is not settled by asking again and getting the same answer")
        self.assertEqual([d["aspect"] for d in live], ["identity"])

    def _merged_source(self, cid):
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        return r["stages"]["research"]["output"]["sources"][0], r

    def _raise_identity_conflict(self, cid):
        key = self._key(self._run(cid))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no"))
        engine.runner("pipe", cid).save(r)
        rec = self._run(cid)
        return key, rec["stages"]["research"]["attribution"][key]["fingerprint"]

    def _decide(self, cid, key, dkey, chosen, fingerprint, **over):
        r = engine.runner("pipe", cid).load()
        d = {"by": "A Person", "at": "2026-10-01T00:00:00Z", "chosen": chosen,
             "becauseWords": "the masthead names the author", "reason": "read the document",
             "evidenceFingerprint": fingerprint}
        d.update(over)
        r["stages"]["research"]["attributionResolutions"] = {key: {dkey: d}}
        engine.runner("pipe", cid).save(r)

    def test_only_a_person_s_recorded_decision_clears_a_disagreement(self):
        f, cid, rec = begin("attrib-resolution")
        key, fp = self._raise_identity_conflict(cid)
        s_, _ = self._merged_source(cid)
        self.assertTrue(s_["attribution"].get("unresolvedDisagreements"))

        # An incomplete decision is not a decision: each of these is missing something a person has to supply.
        for partial in ({"by": ""}, {"becauseWords": ""}, {"reason": ""}, {"at": ""},
                        {"evidenceFingerprint": "a-different-fingerprint"}, {"chosen": "probably"}, {"chosen": ""}):
            self._decide(cid, key, "identity", partial.pop("chosen", "yes"), fp, **partial)
            s_, _ = self._merged_source(cid)
            self.assertTrue(s_["attribution"].get("unresolvedDisagreements"),
                            f"{partial} is not a decision anyone can audit")

        self._decide(cid, key, "identity", "yes", fp)
        s_, _ = self._merged_source(cid)
        self.assertFalse(s_["attribution"].get("unresolvedDisagreements"), "a complete decision settles it")
        self.assertEqual(s_["attribution"]["decidedByAPerson"][0]["by"], "A Person")
        self.assertEqual(s_["attribution"]["detail"]["identity_correct"], "yes")

    def test_a_person_choosing_no_is_not_reduced_to_clearing_the_warning(self):
        """Choosing "no" used to remove the sign of trouble and leave the effective verdict at "yes" — the worst
        of both, because the claim then looked settled in Loom's favour precisely because someone rejected it."""
        f, cid, rec = begin("attrib-resolution-no")
        key, fp = self._raise_identity_conflict(cid)
        self._decide(cid, key, "identity", "no", fp)
        s_, _ = self._merged_source(cid)
        att = s_["attribution"]
        self.assertFalse(att.get("unresolvedDisagreements"), "the question is settled")
        self.assertEqual(att["detail"]["identity_correct"], "no", "and settled the way the person settled it")
        self.assertEqual(att["verdict"], "no", "the aggregate follows the decision, not the model's last answer")
        self.assertEqual(s_["originalSource"]["status"], "not_verified",
                         "a rejected identity cannot leave the source badged as a verified original")
        self.assertIsNotNone(att.get("theModelsOwnAnswer"), "what the model said is kept beside the decision")

    def test_a_decision_takes_effect_without_another_model_call(self):
        f, cid, rec = begin("attrib-resolution-nocall")
        key, fp = self._raise_identity_conflict(cid)
        before = len(log(f))
        self._decide(cid, key, "identity", "no", fp)
        s_, _ = self._merged_source(cid)
        self.assertEqual(s_["attribution"]["detail"]["identity_correct"], "no", "the decision is already in force")
        self.assertEqual(len(log(f)), before, "and nothing was asked of the model to put it there")

    def test_a_decision_made_on_evidence_that_has_since_changed_reopens_the_question(self):
        f, cid, rec = begin("attrib-resolution-stale")
        key, fp = self._raise_identity_conflict(cid)
        self._decide(cid, key, "identity", "yes", fp)
        s_, _ = self._merged_source(cid)
        self.assertFalse(s_["attribution"].get("unresolvedDisagreements"))
        # The page changes under the decision. It was a decision about something else.
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        cur = dict(rs["attribution"][key])
        rs["attribution"][key] = dict(cur, fingerprint="the-evidence-moved-on")
        engine.runner("pipe", cid).save(r)
        s_, _ = self._merged_source(cid)
        self.assertNotEqual(s_["attribution"].get("verdict"), "yes",
                            "a decision does not carry over to evidence it was not made on")

    def test_the_history_keeps_what_the_model_said_whatever_a_person_decided(self):
        f, cid, rec = begin("attrib-resolution-history")
        key, fp = self._raise_identity_conflict(cid)
        self._decide(cid, key, "identity", "no", fp)
        self._merged_source(cid)
        hist = engine.runner("pipe", cid).load()["stages"]["research"]["attributionHistory"][key]
        self.assertTrue(any(h.get("detail", {}).get("identity_correct") == "yes" for h in hist),
                        "the model's own answers are not edited by a later decision")


class EveryClaimReachesTheReviewer(unittest.TestCase):
    """What a reviewer was not shown is not the same as what a document does not say.

    The passage builder kept only the first three relationships per source while `lineage_given` still listed them
    all, and the judge rules said to answer "no" where no passage was shown. On the acceptance course S3, S14, S15
    and S30 claim 4 relationships each and S108 claims 9, so exactly 10 entries sat in that gap: Loom declined to
    show them and the rules invited the reviewer to record them as absent from the document.
    """

    def _src(self, n, words):
        return {"id": "S108", "url": "https://e.org/p",
                "lineage": [{"relation": "extended", "earlier_work": f"work number {i}",
                             "supporting_words": words[i]} for i in range(n)]}

    def _text(self, parts):
        out, filler = [], "filler of no interest here. " * 30
        for w in parts:
            out.append(filler + w)
        return " ".join(out) + filler

    def test_all_nine_relationships_are_covered_not_only_the_first_three(self):
        from loom_server import prompts
        words = [f"this work extends the specification numbered {i} in several respects" for i in range(9)]
        got = prompts.attribution_reviewer_input(self._src(9, words), self._text(words))[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertEqual(len(got), 9, "every claimed relationship gets an entry")
        self.assertTrue(all(g["inspected"] for g in got), "and every one of them was actually looked up")
        self.assertTrue(all(g["found_in_retrieved_text"] for g in got))
        for i, g in enumerate(got):
            self.assertIn(words[i], g["passage"], f"relationship {i} is shown its own words")

    def test_the_whole_set_of_passages_stays_within_a_bounded_budget(self):
        from loom_server import prompts
        words = [f"this work extends the specification numbered {i} in several respects" for i in range(9)]
        got = prompts.attribution_reviewer_input(self._src(9, words), self._text(words))[
            "the_passages_that_show_each_claimed_relationship"]
        total = sum(len(g["passage"] or "") for g in got)
        self.assertLessEqual(total, prompts._RELATION_PASSAGE_BUDGET + 9 * 80,
                             "covering them all must not let one citing page run away with the request")

    def test_what_was_not_looked_up_says_so_and_is_not_read_as_absent(self):
        """The one case where a claim still cannot be shown: so many that no window is big enough to judge from."""
        from loom_server import prompts
        n = 40
        words = [f"this work extends the specification numbered {i} in several respects" for i in range(n)]
        got = prompts.attribution_reviewer_input(self._src(n, words), self._text(words))[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertEqual(len(got), n, "nothing is dropped from the list, whatever the budget")
        skipped = [g for g in got if not g["inspected"]]
        self.assertTrue(skipped, "with 40 claims some cannot be shown")
        for g in skipped:
            self.assertIsNone(g["found_in_retrieved_text"], "not inspected is neither found nor not found")
            self.assertIn("NOT INSPECTED", g["note"])
            self.assertIn("cannot_tell", g["note"], "the reviewer is told what to answer")
            self.assertIn("Do NOT answer 'no'", g["note"], "and told what an omission is not")

    def test_a_claim_loom_could_not_find_is_still_distinguished_from_one_it_did_not_look_for(self):
        from loom_server import prompts
        words = ["this work extends the specification numbered 0 in several respects",
                 "a sentence that appears nowhere in the retrieved document at all"]
        got = prompts.attribution_reviewer_input(self._src(2, words), self._text(words[:1]))[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertEqual([g["inspected"] for g in got], [True, True])
        self.assertEqual([g["found_in_retrieved_text"] for g in got], [True, False])
        self.assertIn("NOT found", got[1]["note"])
        self.assertNotIn("NOT INSPECTED", got[1]["note"], "Loom did look: it is absent, not unexamined")

    def test_the_rules_never_tell_the_reviewer_to_read_an_omission_as_a_denial(self):
        from loom_server import prompts
        p, _ = prompts.attribution_review({"topics": ["t"], "outcome": "o"}, {"nodes": []}, [], {})
        self.assertIn("Answer 'cannot_tell' where 'inspected' is false", p)
        self.assertIn("it is NOT a statement that the document lacks it", p)


class TheIdentityEvidenceIsShown(unittest.TestCase):
    """Identity was judged without the words the identity was read from.

    `identityRead.wordsThatShowIt` is the one field that bears directly on who made the work, and it never reached
    the reviewer: identity rested on the opening of the document, the window around the claim's quotation, and
    whatever a relationship passage happened to include.
    """

    def test_the_words_the_identity_was_read_from_reach_the_reviewer(self):
        from loom_server import prompts
        words = "This report was prepared by Ada Ito of the Institute for Measurement"
        text = ("filler of no interest. " * 300) + words + (" and the report continues. " * 20)
        s_ = {"id": "S1", "url": "https://e.org/p", "directHead": text[:1200], "directExcerpt": "unrelated",
              "identityRead": {"wordsThatShowIt": words}}
        got = prompts.attribution_reviewer_input(s_, text)["the_passage_the_identity_was_read_from"]
        self.assertTrue(got["found_in_retrieved_text"])
        self.assertIn(words, got["passage"])
        self.assertEqual(got["character_offset_in_the_document"], text.index(words))

    def test_an_identity_resting_on_words_not_in_the_document_says_so(self):
        from loom_server import prompts
        s_ = {"id": "S1", "url": "https://e.org/p", "identityRead": {"wordsThatShowIt": "written by someone the page never names"}}
        got = prompts.attribution_reviewer_input(s_, "the document says something else entirely " * 20)
        self.assertFalse(got["the_passage_the_identity_was_read_from"]["found_in_retrieved_text"])
        self.assertIn("does not rest on anything Loom can show you",
                      got["the_passage_the_identity_was_read_from"]["note"])

    def test_the_identity_evidence_is_covered_by_the_fingerprint_like_everything_else_shown(self):
        from loom_server.engine import content_print, attribution_material
        text = "written by Ada Ito of the Institute for Measurement, and the report continues at some length here"
        base = {"id": "S1", "url": "https://e.org/p", "identityRead": {"wordsThatShowIt": "written by Ada Ito of the Institute"}}
        before = content_print(attribution_material(base, text))
        changed = {"id": "S1", "url": "https://e.org/p", "identityRead": {"wordsThatShowIt": "of the Institute for Measurement"}}
        self.assertNotEqual(content_print(attribution_material(changed, text)), before,
                            "a field shown to the reviewer must move the fingerprint")


class AQuoteIsNotAMeaning(unittest.TestCase):
    """A passage can contain the quoted words and still not support the relationship claimed.

    The rule said a relationship whose passage shows the words is 'yes'. Finding the words is where judging starts.
    The S3 case on the acceptance course is the live example: the words support an acknowledgement of an
    open-source teaching curriculum, while the identifier recorded beside them is a journal paper about lessons
    learned. The quotation is genuine and the relationship it is offered for is the wrong one.
    """

    def _rules(self):
        from loom_server import prompts
        return prompts.attribution_review({"topics": ["t"], "outcome": "o"}, {"nodes": []}, [], {})[0]

    def test_the_rules_require_the_relation_itself_not_merely_the_words(self):
        p = self._rules()
        self.assertIn("FINDING THE WORDS IS WHERE YOU START, NOT WHERE YOU FINISH", p)
        self.assertNotIn("A relationship whose passage shows the words is 'yes'", p, "the old rule is gone")

    def test_the_rules_name_relation_direction_chronology_and_the_right_work(self):
        p = self._rules()
        for needed in ("(1) RELATION", "(2) DIRECTION", "(3) CHRONOLOGY", "(4) THE RIGHT WORK"):
            self.assertIn(needed, p, needed)

    def test_a_citation_or_a_see_also_is_named_as_not_being_descent(self):
        p = self._rules()
        self.assertIn("see also", p.lower())
        self.assertIn("reading list", p.lower())

    def test_the_reverse_direction_is_named_as_a_different_claim(self):
        self.assertIn("was later extended by", self._rules(), "the opposite direction is spelled out")

    def test_a_curriculum_offered_for_a_paper_is_named_as_the_wrong_work(self):
        p = self._rules()
        self.assertIn("curriculum", p.lower())
        self.assertIn("even when the words match exactly", p)


class TheWholeRequestIsRecorded(unittest.TestCase):
    """A hash can say two runs differed. Only the request can say how.

    `content_print([p, schema])` left out prompts.SYSTEM, which every call carries, and the settings the model
    runs under, so two runs made under different configuration compared as the identical request. And only
    hashes and a character count were saved, never the ask itself, so an old judgement could not be read back
    against what produced it.
    """

    def _run(self, cid):
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        return wait(cid)

    def test_the_system_text_and_the_settings_are_part_of_the_request_fingerprint(self):
        from loom_server import prompts, engine as E
        p, schema = "the prompt", {"a": 1}
        settings = E.request_settings()
        full = E.content_print({"prompt": p, "schema": schema, "system": prompts.SYSTEM, "settings": settings})
        self.assertNotEqual(full, E.content_print([p, schema]), "the old fingerprint covered less than the request")
        changed = E.content_print({"prompt": p, "schema": schema, "system": prompts.SYSTEM + " and one more rule",
                                   "settings": settings})
        self.assertNotEqual(changed, full, "changing the judge's standing instructions changes the request")
        other = E.content_print({"prompt": p, "schema": schema, "system": prompts.SYSTEM,
                                 "settings": dict(settings, model="some-other-model")})
        self.assertNotEqual(other, full, "a different model is a different ask")

    def test_the_whole_request_is_kept_and_can_be_read_back(self):
        f, cid, rec = begin("request-snapshot")
        rec = self._run(cid)
        rs = rec["stages"]["research"]
        prov = rs["attributionHistory"][next(iter(rs["attributionHistory"]))][-1]["provenance"]
        self.assertTrue(prov.get("requestSnapshot"), "the run says where its request was kept")
        got = storage.read_request_snapshot("pipe", cid, prov["requestFingerprint"])
        self.assertIsNotNone(got, "and the request really is there")
        for field in ("prompt", "schema", "system", "settings", "requestFingerprint", "sourcesInRequest", "build"):
            self.assertIn(field, got, field)
        self.assertEqual(got["requestFingerprint"], prov["requestFingerprint"])
        self.assertEqual(len(got["prompt"]), prov["promptCharacters"], "the kept prompt is the one that was sent")

    def test_one_request_is_kept_once_however_many_sources_it_judged(self):
        f, cid, rec = begin("request-snapshot-once")
        rec = self._run(cid)
        d = storage.course_dir("pipe", cid) / "requests"
        self.assertEqual(len(list(d.glob("*.json"))), 1, "a batch is one request, not one per source")
        self.assertGreater(len(rec["stages"]["research"]["attributionHistory"]), 1, "and it judged several sources")

    def test_a_kept_request_is_never_rewritten(self):
        f, cid, rec = begin("request-immutable")
        rec = self._run(cid)
        rs = rec["stages"]["research"]
        fp = rs["attributionHistory"][next(iter(rs["attributionHistory"]))][-1]["provenance"]["requestFingerprint"]
        storage.save_request_snapshot("pipe", cid, fp, {"prompt": "something else entirely"})
        self.assertNotEqual(storage.read_request_snapshot("pipe", cid, fp)["prompt"], "something else entirely",
                            "a snapshot that could be replaced is not a record of what was asked")

    def test_equal_evidence_equal_request_and_equal_execution_are_kept_apart(self):
        f, cid, rec = begin("three-fingerprints")
        rec = self._run(cid)
        rs = rec["stages"]["research"]
        prov = rs["attributionHistory"][next(iter(rs["attributionHistory"]))][-1]["provenance"]
        for field in ("batchInputFingerprint", "requestFingerprint", "settingsFingerprint", "settings",
                      "build", "buildOfFilesOnDiskNow", "filesChangedSinceStart"):
            self.assertIn(field, prov, field)
        self.assertNotEqual(prov["batchInputFingerprint"], prov["requestFingerprint"],
                            "the evidence is not the request")

    def test_the_running_build_is_distinguished_from_the_files_on_disk(self):
        from loom_server import engine as E
        got = E._execution_provenance()
        self.assertIn("build", got)
        self.assertIn("buildOfFilesOnDiskNow", got)
        self.assertIsInstance(got["filesChangedSinceStart"], bool)


class NoJudgementIsEverDeleted(unittest.TestCase):
    """`del past[:-20]` destroyed every judgement older than the last twenty, under a rule saying every one is kept."""

    def _run(self, cid):
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        return wait(cid)

    def test_judgements_leaving_the_working_index_are_kept_in_full_beside_the_course(self):
        from loom_server import engine as E
        f, cid, rec = begin("history-durable")
        rec = self._run(cid)
        rs = rec["stages"]["research"]
        key = next(iter(rs["attributionHistory"]))

        # Push the working index past its limit with judgements that can be told apart afterwards.
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        base = h[-1]
        h[:] = [dict(base, runId=f"run-{i:03d}", at=f"2026-09-{(i % 28) + 1:02d}T00:00:00Z") for i in range(25)]
        engine.runner("pipe", cid).save(r)
        rec = self._run(cid)

        rs = rec["stages"]["research"]
        inline = rs["attributionHistory"][key]
        self.assertLessEqual(len(inline), E._HISTORY_INDEX_KEEP, "the working index stays bounded")
        moved = rs["attributionHistoryArchived"][key]
        self.assertGreater(moved["count"], 0, "and says how many left it")
        archived = storage.read_archived_judgements("pipe", cid, key)
        self.assertEqual(len(archived), moved["count"], "every one of them is still readable")
        kept = {e.get("runId") for e in archived} | {e.get("runId") for e in inline}
        for i in range(25):
            self.assertIn(f"run-{i:03d}", kept, f"run-{i:03d} was destroyed")

    def test_the_archive_is_appended_to_and_never_rewritten(self):
        f, cid, rec = begin("history-append")
        rec = self._run(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        storage.archive_judgements("pipe", cid, key, [{"runId": "first"}])
        storage.archive_judgements("pipe", cid, key, [{"runId": "second"}])
        got = [e.get("runId") for e in storage.read_archived_judgements("pipe", cid, key)]
        self.assertEqual(got, ["first", "second"], "the earlier one is still there")


class OneSpellingOfTheAddress(unittest.TestCase):
    """The reviewer saw the raw URL while the fingerprint covered the normalised one."""

    def test_the_reviewer_and_the_fingerprint_see_the_same_address(self):
        from loom_server import prompts
        from loom_server.engine import content_print, attribution_material
        a, b = {"id": "S1", "url": "https://E.org/a/"}, {"id": "S1", "url": "https://e.org/a"}
        self.assertEqual(prompts.attribution_reviewer_input(a)["url"], prompts.attribution_reviewer_input(b)["url"])
        self.assertEqual(content_print(attribution_material(a)), content_print(attribution_material(b)),
                         "one record, one request: not the same record asked two different ways")



class TheWriterIsToldWhatIsContested(unittest.TestCase):
    """A writer shown only the aggregate verdict cannot tell a settled claim from a contested one.

    `attribution_review_verdict` reads "yes" for a source whose identity two runs answered differently, so a
    lesson could present a contested point as established fact and nobody reading the lesson would know.
    """

    def _row(self, attribution):
        from loom_server import prompts
        s_ = {"id": "S1", "title": "A later work", "url": "https://e.org/b", "claim": "c", "finding": "f",
              "quote": "we repeated the earlier study", "strength": "direct", "role": "primary_extension",
              "authors": ["Bo Okafor"], "published": "2005", "attribution": attribution, "node_ids": ["N1"],
              "lineage": [{"relation": "replicated", "earlier_work": "A first report",
                           "supporting_words": "we repeated the earlier study", "what_changed": "repeated it"}]}
        return prompts.sources_digest({"sources": [s_]})[0]

    def test_a_contested_source_is_flagged_beside_its_verdict(self):
        row = self._row({"verdict": "yes", "unresolvedDisagreements": [
            {"aspect": "identity", "key": "identity", "earlier": "no", "later": "yes"}]})
        self.assertEqual(row["attribution_review_verdict"], "yes", "the aggregate verdict on its own looks settled")
        got = row.get("the_attribution_review_disagrees_with_itself")
        self.assertTrue(got, "and that is exactly why the contradiction has to travel with it")
        self.assertEqual(got[0]["about"], "identity")
        self.assertEqual((got[0]["earlier_answer"], got[0]["later_answer"]), ("no", "yes"))

    def test_a_settled_source_carries_no_such_flag(self):
        row = self._row({"verdict": "yes"})
        self.assertNotIn("the_attribution_review_disagrees_with_itself", row)

    def test_the_writer_rules_say_a_contested_claim_is_not_a_weaker_yes(self):
        from loom_server import prompts
        rules = prompts.SOURCES_NOTE
        self.assertIn("the_attribution_review_disagrees_with_itself", rules)
        self.assertIn("It is NOT a weaker yes and it is NOT a no", rules)
        self.assertIn("do not pick the answer that suits the lesson", rules)


class DecidingNeedsNoModel(unittest.TestCase):
    """The endpoint a person uses to settle a disagreement the review left open.

    It is deliberately not an engine action. Engine actions refuse when the Claude tool is not ready, and
    deciding between two answers the review already gave needs no model: spending one would produce a third
    answer, not a decision about the first two.
    """

    def _ready(self):
        f, cid, rec = begin("decide-endpoint")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no"))
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        wait(cid)
        return f, cid, key

    def _seen(self, cid, key, dkey="identity"):
        """What the screen would be showing: the evidence and the version of the question."""
        rec = engine.runner("pipe", cid).load()
        entry = rec["stages"]["research"]["attribution"][key]
        q = next((x for x in engine.open_questions(entry) if x["key"] == dkey), None)
        return entry.get("fingerprint"), (q or {}).get("revision")

    def _decide(self, cid, key, **over):
        ev, rev = self._seen(cid, key)
        d = {"by": "A Person", "chosen": "no", "becauseWords": "the masthead names the author",
             "reason": "read the document", "sawEvidence": ev, "sawRevision": rev}
        d.update(over)
        return engine.record_resolution("pipe", cid, key, "identity", d)

    def test_a_decision_is_recorded_and_changes_the_effective_judgement(self):
        f, cid, key = self._ready()
        got = self._decide(cid, key)
        self.assertEqual(got["chosen"], "no")
        self.assertTrue(got["at"], "a decision says when it was made")
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        att = r["stages"]["research"]["output"]["sources"][0]["attribution"]
        self.assertEqual(att["detail"]["identity_correct"], "no")
        self.assertEqual(att["verdict"], "no", "choosing no is not reduced to clearing the warning")

    def test_an_incomplete_or_unrecognised_decision_is_refused(self):
        f, cid, key = self._ready()
        for bad in ({"by": ""}, {"becauseWords": "   "}, {"reason": ""}, {"chosen": ""}, {"chosen": "probably"}):
            with self.assertRaises(storage.StoreError, msg=str(bad)):
                self._decide(cid, key, **bad)

    def test_a_question_that_is_not_open_cannot_be_decided(self):
        f, cid, key = self._ready()
        ev, rev = self._seen(cid, key)
        base = {"by": "A", "chosen": "yes", "becauseWords": "w", "reason": "r",
                "sawEvidence": ev, "sawRevision": rev}
        with self.assertRaises(storage.StoreError):
            engine.record_resolution("pipe", cid, key, "role", base)
        with self.assertRaises(storage.StoreError):
            engine.record_resolution("pipe", cid, "no-such-claim", "identity", base)

    def test_a_second_decision_does_not_silently_overwrite_the_first(self):
        f, cid, key = self._ready()
        first = self._decide(cid, key, chosen="no")
        with self.assertRaises(storage.Conflict):
            self._decide(cid, key, chosen="yes")
        got = self._decide(cid, key, chosen="yes", replacing=first["decisionId"])
        self.assertEqual(got["replaces"], first["decisionId"], "it names the decision it replaced")
        hist = engine.decision_history(engine.runner("pipe", cid).load(), key, "identity")
        self.assertEqual([h["chosen"] for h in hist], ["no", "yes"], "both are kept in full, in order")

    def test_deciding_asks_nothing_of_the_model_and_approves_nothing(self):
        f, cid, key = self._ready()
        before, status_before = len(log(f)), engine.runner("pipe", cid).load().get("status")
        self._decide(cid, key)
        rec = engine.runner("pipe", cid).load()
        self.assertEqual(len(log(f)), before, "no request was sent to Claude")
        self.assertEqual(rec.get("status"), status_before, "the course did not move stage")
        self.assertIsNot(rec.get("approved"), True, "and nothing was approved")


class TheEvidenceBudgetIsActuallyKept(unittest.TestCase):
    """A claimed quotation of any length used to become the passage, bypassing the budget entirely."""

    def test_one_enormous_quotation_cannot_exceed_the_window(self):
        from loom_server import prompts
        huge = "z" * 9000
        s_ = {"id": "S9", "url": "https://e.org/p",
              "lineage": [{"relation": "extended", "earlier_work": "W", "supporting_words": huge}]}
        got = prompts.attribution_reviewer_input(s_, "prefix " + huge + " suffix")[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertLessEqual(len(got[0]["passage"]), prompts._RELATION_WINDOW)
        self.assertIn("not all of it", got[0]["note"], "the reviewer is told it is seeing part of the quotation")
        self.assertIn("cannot_tell", got[0]["note"])

    def test_the_whole_set_stays_within_budget_even_when_every_quotation_is_enormous(self):
        from loom_server import prompts
        words = ["q" * 9000 + str(i) for i in range(9)]
        s_ = {"id": "S9", "url": "https://e.org/p",
              "lineage": [{"relation": "extended", "earlier_work": f"W{i}", "supporting_words": w}
                          for i, w in enumerate(words)]}
        got = prompts.attribution_reviewer_input(s_, " ".join(words))[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertLessEqual(sum(len(g["passage"] or "") for g in got), prompts._RELATION_PASSAGE_BUDGET)

    def test_the_words_claimed_are_still_reported_in_full_length_terms(self):
        from loom_server import prompts
        s_ = {"id": "S9", "url": "https://e.org/p",
              "lineage": [{"relation": "extended", "earlier_work": "W", "supporting_words": "z" * 9000}]}
        got = prompts.attribution_reviewer_input(s_, "z" * 9000)[
            "the_passages_that_show_each_claimed_relationship"]
        self.assertLessEqual(len(got[0]["words_claimed"]), 300, "the claim itself is also bounded")
        self.assertIn("9000 characters long", got[0]["note"], "but its real length is not hidden")


class TheSourceBadgeAgreesWithTheGraph(unittest.TestCase):
    """"Original source verified" appeared beside a work the graph was holding at an unresolved identity."""

    def _src(self):
        words = "we introduce the method described here"
        return {"id": "S1", "url": "https://e.org/a", "title": "A first report", "authors": ["Ada Ito"],
                "published": "1998", "identifier": "doi:10.1234/first", "role": "original_contribution",
                "quote": words, "evidenceLevel": "direct_text_quote_found",
                "directRetrieval": {"sha256": "a" * 64, "quoteVerbatim": True,
                                    "locator": {"charStart": 0, "charEnd": 9}},
                "directExcerpt": words + " and more", "lineage": [],
                "attribution": {"verdict": "yes",
                                "detail": {"identity_correct": "yes", "role_correct": "yes",
                                           "lineage_supported": "none_claimed"},
                                "unresolvedDisagreements": [{"aspect": "identity", "key": "identity",
                                                             "earlier": "no", "later": "yes"}]}}

    def test_a_contested_identity_is_not_badged_as_a_verified_original(self):
        from loom_server import evidence, lineage
        s_ = self._src()
        badge = evidence.original_status(s_, "yes")
        work = next(iter(lineage.build([s_])["works"].values()))
        self.assertEqual(badge["status"], "not_verified")
        self.assertEqual(work["originStatus"], "unknown")
        self.assertTrue(any("disagree" in b for b in badge["because"]), badge["because"])

    def test_an_unreadable_disagreement_record_also_withholds_the_badge(self):
        from loom_server import evidence
        s_ = self._src()
        s_["attribution"]["unresolvedDisagreements"] = "not a list"
        self.assertEqual(evidence.original_status(s_, "yes")["status"], "not_verified")

    def test_a_settled_source_still_earns_the_badge(self):
        from loom_server import evidence
        s_ = self._src()
        s_["attribution"].pop("unresolvedDisagreements")
        self.assertEqual(evidence.original_status(s_, "yes")["status"], "verified")


class DecisionsAreBoundToWhatWasSeen(unittest.TestCase):
    """A decision is about what a person read on the screen, not about whatever the record has since become."""

    def _ready(self):
        f, cid, rec = begin("decide-bound")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no"))
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        wait(cid)
        return f, cid, key

    def _seen(self, cid, key):
        entry = engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key]
        q = next(x for x in engine.open_questions(entry) if x["key"] == "identity")
        return entry["fingerprint"], q["revision"]

    def _send(self, cid, key, **over):
        ev, rev = self._seen(cid, key)
        d = {"by": "P", "chosen": "yes", "becauseWords": "w", "reason": "r",
             "sawEvidence": ev, "sawRevision": rev}
        d.update(over)
        return engine.record_resolution("pipe", cid, key, "identity", d)

    def test_a_decision_that_does_not_say_what_it_saw_is_refused(self):
        f, cid, key = self._ready()
        for missing in ({"sawEvidence": ""}, {"sawRevision": ""}, {"sawEvidence": "", "sawRevision": ""}):
            with self.assertRaises(storage.StoreError, msg=str(missing)):
                self._send(cid, key, **missing)

    def test_a_decision_made_on_evidence_that_has_since_moved_is_refused_not_restamped(self):
        f, cid, key = self._ready()
        old_ev, old_rev = self._seen(cid, key)
        r = engine.runner("pipe", cid).load()
        r["stages"]["research"]["attribution"][key]["fingerprint"] = "the-evidence-moved-on"
        engine.runner("pipe", cid).save(r)
        with self.assertRaises(storage.Conflict):
            self._send(cid, key, sawEvidence=old_ev, sawRevision=old_rev)
        rec = engine.runner("pipe", cid).load()
        self.assertFalse((rec["stages"]["research"].get("attributionResolutions") or {}).get(key),
                         "nothing was written, and certainly not stamped with evidence nobody saw")

    def test_a_decision_about_an_older_version_of_the_question_is_refused(self):
        f, cid, key = self._ready()
        _, old_rev = self._seen(cid, key)
        r = engine.runner("pipe", cid).load()
        live = r["stages"]["research"]["attribution"][key]["unresolvedDisagreements"]
        live[0] = dict(live[0], later="partly")
        engine.runner("pipe", cid).save(r)
        ev, _ = self._seen(cid, key)
        with self.assertRaises(storage.Conflict):
            self._send(cid, key, sawEvidence=ev, sawRevision=old_rev)

    def test_two_genuinely_overlapping_decisions_do_not_both_succeed(self):
        """Both read the same state, both find themselves allowed to write, and the second silently replaces
        the first. Sequential submissions never showed this; only an actual overlap does."""
        import threading
        f, cid, key = self._ready()
        ev, rev = self._seen(cid, key)
        gate, out = threading.Barrier(2, timeout=10), []

        def go(chosen):
            try:
                gate.wait()
                out.append(("ok", engine.record_resolution("pipe", cid, key, "identity", {
                    "by": "P", "chosen": chosen, "becauseWords": "w", "reason": "r",
                    "sawEvidence": ev, "sawRevision": rev})["chosen"]))
            except Exception as e:
                out.append(("refused", type(e).__name__))

        ts = [threading.Thread(target=go, args=(c,)) for c in ("yes", "no")]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=20)
        self.assertEqual(sum(1 for k, _ in out if k == "ok"), 1, f"exactly one may win: {out}")
        self.assertEqual(sum(1 for k, _ in out if k == "refused"), 1, f"the other is told, not dropped: {out}")
        hist = engine.decision_history(engine.runner("pipe", cid).load(), key, "identity")
        self.assertEqual(len(hist), 1, "and only the one that won was written")

    def test_a_decision_is_refused_while_a_job_is_running_on_the_course(self):
        f, cid, key = self._ready()
        ev, rev = self._seen(cid, key)
        r = engine.runner("pipe", cid).load()
        r["status"] = "running"
        engine.runner("pipe", cid).save(r)
        try:
            with self.assertRaises(storage.Conflict):
                self._send(cid, key, sawEvidence=ev, sawRevision=rev)
        finally:
            r = engine.runner("pipe", cid).load()
            r["status"] = "paused"
            engine.runner("pipe", cid).save(r)


class EveryDecisionIsKeptInFull(unittest.TestCase):
    """Keeping the newest and a shortened note of the one before threw away the quotations and the reasons."""

    def _ready(self):
        f, cid, rec = begin("decide-history")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no"))
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        wait(cid)
        return f, cid, key

    def _decide(self, cid, key, chosen, because, reason, replacing=None):
        entry = engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key]
        q = next(x for x in engine.open_questions(entry) if x["key"] == "identity")
        return engine.record_resolution("pipe", cid, key, "identity", {
            "by": "P", "chosen": chosen, "becauseWords": because, "reason": reason,
            "sawEvidence": entry["fingerprint"], "sawRevision": q["revision"], "replacing": replacing})

    def test_three_successive_decisions_are_all_kept_with_their_words_and_reasons(self):
        f, cid, key = self._ready()
        prev = None
        for chosen, because, reason in (("yes", "the masthead names Ito", "first reading"),
                                        ("partly", "the preface hedges it", "second reading"),
                                        ("no", "the erratum retracts it", "third reading")):
            prev = self._decide(cid, key, chosen, because, reason, replacing=prev)["decisionId"]
        hist = engine.decision_history(engine.runner("pipe", cid).load(), key, "identity")
        self.assertEqual([h["chosen"] for h in hist], ["yes", "partly", "no"])
        self.assertEqual([h["becauseWords"] for h in hist],
                         ["the masthead names Ito", "the preface hedges it", "the erratum retracts it"])
        self.assertEqual([h["reason"] for h in hist], ["first reading", "second reading", "third reading"])

    def test_each_decision_has_its_own_identity_and_order_whatever_the_clock_says(self):
        f, cid, key = self._ready()
        a = self._decide(cid, key, "yes", "w1", "r1")
        b = self._decide(cid, key, "no", "w2", "r2", replacing=a["decisionId"])
        self.assertNotEqual(a["decisionId"], b["decisionId"], "two decisions are never the same decision")
        self.assertEqual([a["sequence"], b["sequence"]], [1, 2], "order does not depend on the timestamp")
        self.assertEqual(b["replaces"], a["decisionId"], "and it names the one it replaced, not a time")

    def test_the_models_own_answers_are_kept_apart_from_the_decisions(self):
        f, cid, key = self._ready()
        self._decide(cid, key, "no", "the erratum retracts it", "read it")
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        att = r["stages"]["research"]["output"]["sources"][0]["attribution"]
        self.assertEqual(att["detail"]["identity_correct"], "no", "the decision governs")
        self.assertEqual(att["theModelsOwnAnswer"]["detail"]["identity_correct"], "yes", "the model's is kept")
        hist = r["stages"]["research"]["attributionHistory"][key]
        self.assertTrue(any(h.get("detail", {}).get("identity_correct") == "yes" for h in hist))

    def test_the_decision_history_survives_a_backup_and_restore(self):
        f, cid, key = self._ready()
        self._decide(cid, key, "no", "the erratum retracts it", "read it")
        new = storage.restore("pipe", storage.backup("pipe", cid))["id"]
        hist = engine.decision_history(storage.read_engine("pipe", new), key, "identity")
        self.assertEqual([h["chosen"] for h in hist], ["no"])
        self.assertEqual(hist[0]["becauseWords"], "the erratum retracts it")

    def test_the_decision_history_survives_a_copy(self):
        f, cid, key = self._ready()
        self._decide(cid, key, "no", "the erratum retracts it", "read it")
        new = storage.duplicate_course("pipe", cid)["id"]
        self.assertEqual(len(engine.decision_history(storage.read_engine("pipe", new), key, "identity")), 1)


class ProvenanceRecordsTheWholeInvocation(unittest.TestCase):
    """What answered, under what configuration, and what happens when two requests share a fingerprint."""

    def test_the_settings_name_the_tool_build_and_the_limits_it_ran_under(self):
        from loom_server import engine as E
        got = E.request_settings()
        for field in ("model", "effort", "testDouble", "cliVersion", "turns", "timeoutSeconds"):
            self.assertIn(field, got, field)
        self.assertNotEqual(E.content_print(got), E.content_print({k: v for k, v in got.items()
                                                                   if k != "cliVersion"}),
                            "the tool build is part of the request, not decoration")

    def test_a_different_tool_build_is_a_different_request(self):
        from loom_server import engine as E, prompts
        base = {"prompt": "p", "schema": {}, "system": prompts.SYSTEM, "settings": E.request_settings()}
        other = dict(base, settings=dict(base["settings"], cliVersion="some-other-build"))
        self.assertNotEqual(E.content_print(base), E.content_print(other))

    def test_a_fingerprint_collision_is_reported_rather_than_confused(self):
        f, cid, rec = begin("snapshot-collision")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        prov = rs["attributionHistory"][next(iter(rs["attributionHistory"]))][-1]["provenance"]
        fp = prov["requestFingerprint"]
        self.assertTrue(prov.get("requestSnapshot"), "the first run kept its request")

        # Something else is already stored under this name, and it is not this run's request.
        path = storage.course_dir("pipe", cid) / "requests" / (storage._fp_name(fp) + ".json")
        path.write_text(json.dumps({"prompt": "a completely different request", "schema": {},
                                    "system": "different", "settings": {}}), encoding="utf-8")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        rs = rec["stages"]["research"]
        prov = rs["attributionHistory"][next(iter(rs["attributionHistory"]))][-1]["provenance"]
        # Superseded: discarding this run's request was itself the defect. Both are now kept.
        self.assertTrue(prov["requestSnapshot"], "this run's own request is kept, not dropped")
        self.assertNotEqual(prov["requestSnapshot"], storage._fp_name(fp) + ".json",
                            "under its own name, beside the one already there")
        self.assertIn("Both are kept", prov["fingerprintSharedWithAnotherRequest"])
        self.assertEqual(json.loads(path.read_text())["prompt"], "a completely different request",
                         "and nothing was overwritten")
        mine = json.loads((storage.course_dir("pipe", cid) / "requests" / prov["requestSnapshot"]).read_text())
        self.assertEqual(len(mine["prompt"]), prov["promptCharacters"], "and it really is this run's request")


class AnOlderConflictIsNotForgotten(unittest.TestCase):
    """A conflict raised three runs ago, absent from the latest entry, is still unsettled."""

    def test_a_conflict_in_an_older_entry_is_carried_forward(self):
        f, cid, rec = begin("older-conflict")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))

        # An older judgement on the SAME evidence carried a conflict; the entry after it did not repeat it.
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        old = dict(h[-1], runId="run-older", unresolvedDisagreements=[
            {"aspect": "role", "key": "role", "earlier": "no", "later": "yes",
             "sameEvidence": True, "sameWholeRequest": True, "note": "UNRESOLVED"}])
        h[:] = [old, dict(h[-1], runId="run-newer")]
        engine.runner("pipe", cid).save(r)

        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        live = rec["stages"]["research"]["attribution"][key].get("unresolvedDisagreements") or []
        self.assertIn("role", {d.get("aspect") for d in live},
                      "one run not repeating a conflict does not settle it")


class ADecisionIsNeverOverwrittenByItsOwnDerivedState(unittest.TestCase):
    """Two DIFFERENT questions could both report success while only the first survived.

    The merge that rebuilds the views a decision feeds used to run AFTER the transaction: read the record again,
    merge, write. Anything saved by someone else between that read and that write was overwritten by a record
    that predated it, and both callers were told they had succeeded.
    """

    def _ready(self):
        f, cid, rec = begin("two-questions")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no", role_correct="no"))
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        wait(cid)
        return f, cid, key

    def _send(self, cid, key, dkey, chosen):
        entry = engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key]
        q = next(x for x in engine.open_questions(entry) if x["key"] == dkey)
        return engine.record_resolution("pipe", cid, key, dkey, {
            "by": "P", "chosen": chosen, "becauseWords": "w", "reason": "r",
            "sawEvidence": entry["fingerprint"], "sawRevision": q["revision"]})

    def _state(self, cid, key):
        rs = engine.runner("pipe", cid).load()["stages"]["research"]
        return (sorted((rs.get("attributionResolutions") or {}).get(key, {})),
                [e["question"] for e in rs.get("attributionDecisions") or []])

    def test_two_different_questions_both_survive(self):
        f, cid, key = self._ready()
        self.assertEqual(len(engine.open_questions(
            engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key])), 2)
        self._send(cid, key, "identity", "no")
        self._send(cid, key, "role", "partly")
        kept, events = self._state(cid, key)
        self.assertEqual(kept, ["identity", "role"], "neither decision may be lost")
        self.assertEqual(sorted(events), ["identity", "role"])

    def test_the_views_a_decision_feeds_reflect_both_decisions(self):
        f, cid, key = self._ready()
        self._send(cid, key, "identity", "no")
        self._send(cid, key, "role", "partly")
        r = engine.runner("pipe", cid).load()
        att = r["stages"]["research"]["output"]["sources"][0]["attribution"]
        self.assertEqual({d["about"] for d in att.get("decidedByAPerson") or []}, {"identity", "role"})
        self.assertFalse(att.get("unresolvedDisagreements"), "and nothing is left looking open")

    def test_overlapping_decisions_on_different_questions_both_survive(self):
        import threading
        f, cid, key = self._ready()
        gate, out = threading.Barrier(2, timeout=15), []

        def go(dkey, chosen):
            try:
                gate.wait()
                out.append(("ok", self._send(cid, key, dkey, chosen)["question"]))
            except Exception as e:
                out.append(("refused", type(e).__name__))

        ts = [threading.Thread(target=go, args=a) for a in (("identity", "no"), ("role", "partly"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        kept, events = self._state(cid, key)
        self.assertEqual(sum(1 for k, _ in out if k == "ok"), 2, f"different questions do not conflict: {out}")
        self.assertEqual(kept, ["identity", "role"], f"and both must be on disk: {out}")
        self.assertEqual(len(events), 2)

    def test_a_decision_is_still_refused_once_a_run_starts(self):
        f, cid, key = self._ready()
        r = engine.runner("pipe", cid).load()
        r["status"] = "running"
        engine.runner("pipe", cid).save(r)
        try:
            with self.assertRaises(storage.Conflict):
                self._send(cid, key, "identity", "no")
            self.assertEqual(self._state(cid, key), ([], []), "and nothing was written")
        finally:
            r = engine.runner("pipe", cid).load()
            r["status"] = "paused"
            engine.runner("pipe", cid).save(r)


class AnArchivedConflictIsStillAConflict(unittest.TestCase):
    """A conflict vanished once its history was evicted from the twenty-entry index."""

    def _course(self, name):
        f, cid, rec = begin(name)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        return f, cid, next(iter(rec["stages"]["research"]["attributionHistory"]))

    def test_a_conflict_in_the_archive_is_found_when_the_same_evidence_returns(self):
        f, cid, key = self._course("archived-conflict")
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        entry = rs["attribution"][key]
        fp = entry["fingerprint"]
        # An earlier judgement on THIS evidence carried a conflict, and it has since been archived out of the
        # inline index, which now holds only judgements made on other evidence.
        storage.archive_judgements("pipe", cid, key, [dict(entry, runId="run-ancient", verdict="no",
                                                          unresolvedDisagreements=[
                                                              {"aspect": "role", "key": "role", "earlier": "no",
                                                               "later": "yes", "sameEvidence": True,
                                                               "sameWholeRequest": True, "note": "UNRESOLVED"}])])
        rs["attributionHistory"][key] = [dict(entry, runId=f"other{i}", fingerprint="OTHER-EVIDENCE")
                                         for i in range(20)]
        engine.runner("pipe", cid).save(r)

        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        cur = rec["stages"]["research"]["attribution"][key]
        self.assertEqual(cur["fingerprint"], fp, "the run really is back on the same evidence")
        self.assertIn("role", {d.get("aspect") for d in cur.get("unresolvedDisagreements") or []},
                      "an archived conflict is not a settled one")

    def test_history_that_cannot_be_read_is_reported_rather_than_read_as_no_conflict(self):
        f, cid, key = self._course("unreadable-history")
        import hashlib as _h
        name = "k" + _h.sha256(str(key).encode()).hexdigest()[:24] + ".jsonl"
        d = storage.course_dir("pipe", cid) / "attribution-history"
        d.mkdir(exist_ok=True)
        (d / name).write_text("this is not a judgement\n", encoding="utf-8")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        cur = rec["stages"]["research"]["attribution"][key]
        self.assertTrue(cur.get("historyIncomplete"), "Loom cannot claim there was no earlier disagreement")
        self.assertIn("NOT a statement that there was none", cur["historyIncomplete"]["note"])

    def test_a_resolution_still_applies_after_its_history_is_archived(self):
        f, cid, key = self._course("resolution-after-archive")
        entry = engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key]
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        rs["attribution"][key] = dict(entry, unresolvedDisagreements=[
            {"aspect": "identity", "key": "identity", "earlier": "no", "later": "yes",
             "sameEvidence": True, "sameWholeRequest": True}])
        engine.runner("pipe", cid).save(r)
        q = next(x for x in engine.open_questions(
            engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key]) if x["key"] == "identity")
        engine.record_resolution("pipe", cid, key, "identity", {
            "by": "P", "chosen": "no", "becauseWords": "w", "reason": "r",
            "sawEvidence": entry["fingerprint"], "sawRevision": q["revision"]})
        # Now archive everything and re-read: the decision is still in force.
        r = engine.runner("pipe", cid).load()
        storage.archive_judgements("pipe", cid, key, r["stages"]["research"]["attributionHistory"][key])
        r["stages"]["research"]["attributionHistory"][key] = []
        engine.runner("pipe", cid).save(r)
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        att = r["stages"]["research"]["output"]["sources"][0]["attribution"]
        self.assertEqual(att["detail"]["identity_correct"], "no", "a decision is not undone by archiving")


class UnavailableHistoryIsNotNoHistory(unittest.TestCase):
    """Expected archived judgements that cannot be read must not read as "there were none".

    Missing file, truncated file and refused path all returned a confident `yes` with nothing to say about the
    history Loom had failed to find, and the writer digest, the badge and the graph all repeated that
    confidence.
    """

    def _ready(self, expected=3, write=None, link=False):
        f, cid, rec = begin("history-manifest")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        import hashlib as _h
        name = "k" + _h.sha256(str(key).encode()).hexdigest()[:24] + ".jsonl"
        rs["attributionHistoryArchived"] = {key: {"count": expected, "file": name}}
        rs["attributionHistory"][key] = []
        engine.runner("pipe", cid).save(r)
        d = storage.course_dir("pipe", cid) / "attribution-history"
        d.mkdir(exist_ok=True)
        if link:
            outside = storage.store_dir("pipe").parent / "outside-hist.jsonl"
            outside.write_text('{"runId":"not ours"}\n', encoding="utf-8")
            (d / name).symlink_to(outside)
        elif write is not None:
            (d / name).write_text("".join(json.dumps(dict(rs["attribution"][key], key=key, **json.loads(line))) + "\n" for line in write.splitlines()), encoding="utf-8")
        return f, cid, key

    def _run(self, cid, key):
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        return rec["stages"]["research"]["attribution"][key]

    def test_a_missing_archive_is_reported(self):
        f, cid, key = self._ready(expected=3, write=None)
        got = self._run(cid, key)["historyIncomplete"]
        self.assertEqual((got["expectedArchived"], got["couldRead"]), (3, 0))

    def test_a_truncated_archive_is_reported(self):
        f, cid, key = self._ready(expected=3, write='{"runId":"one"}\n')
        got = self._run(cid, key)["historyIncomplete"]
        self.assertEqual((got["expectedArchived"], got["couldRead"]), (3, 1))
        self.assertTrue(any("only 1 can be read" in w for w in got["why"]), got["why"])

    def test_a_refused_archive_path_is_reported(self):
        f, cid, key = self._ready(expected=3, link=True)
        got = self._run(cid, key)["historyIncomplete"]
        self.assertEqual((got["expectedArchived"], got["couldRead"]), (3, 0))

    def test_a_complete_archive_raises_nothing(self):
        import hashlib as _h
        f, cid, key = self._ready(expected=2, write='{"runId":"a"}\n{"runId":"b"}\n')
        self.assertIsNone(self._run(cid, key).get("historyIncomplete"))

    def test_the_badge_the_writer_the_graph_and_the_export_all_stop_claiming_confidence(self):
        from loom_server import evidence, lineage, prompts
        f, cid, key = self._ready(expected=3, write=None)
        self._run(cid, key)
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        s_ = r["stages"]["research"]["output"]["sources"][0]
        self.assertTrue(s_["attribution"]["historyIncomplete"], "recomputed on read, not only when run")
        self.assertEqual(s_["originalSource"]["status"], "not_verified", "the badge stops saying verified")
        self.assertTrue(any("history is missing" in b for b in s_["originalSource"]["because"]))
        row = prompts.sources_digest({"sources": [s_]})[0]
        self.assertIn("part_of_this_sources_history_is_missing", row, "the writer is told")
        self.assertIn("part_of_this_sources_history_is_missing", prompts.SOURCES_NOTE, "and told what it means")
        w = next(iter(lineage.build([s_])["works"].values()))
        self.assertNotEqual(w["originStatus"], "established", "the graph stops establishing the origin")

    def test_the_flag_clears_once_the_history_can_be_read_again(self):
        import hashlib as _h
        f, cid, key = self._ready(expected=1, write=None)
        self.assertTrue(self._run(cid, key).get("historyIncomplete"))
        name = "k" + _h.sha256(str(key).encode()).hexdigest()[:24] + ".jsonl"
        (storage.course_dir("pipe", cid) / "attribution-history" / name).write_text(
            json.dumps(dict(engine.runner("pipe", cid).load()["stages"]["research"]["attribution"][key], key=key, runId="recovered")) + "\n", encoding="utf-8")
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        self.assertIsNone(r["stages"]["research"]["output"]["sources"][0]["attribution"].get("historyIncomplete"))


class AFailedRebuildPublishesNothing(unittest.TestCase):
    """Merging in place and catching the exception saved whatever the failed merge had already mutated."""

    def _ready(self, name):
        f, cid, rec = begin(name)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no", role_correct="no"))
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        wait(cid)
        return f, cid, key

    def _send(self, cid, key, dkey, chosen):
        rec = engine.runner("pipe", cid).load()
        rs = rec["stages"]["research"]
        entry = rs["attribution"][key]
        q = next(x for x in engine.open_questions(entry, (rs.get("attributionResolutions") or {}).get(key))
                 if x["key"] == dkey)
        return engine.record_resolution("pipe", cid, key, dkey, {
            "by": "P", "chosen": chosen, "becauseWords": "w", "reason": "r",
            "sawEvidence": entry["fingerprint"], "sawRevision": q["revision"],
            "replacing": q.get("replacing")})

    def test_a_merge_that_mutates_then_raises_changes_nothing(self):
        f, cid, key = self._ready("rebuild-fails")
        before = json.dumps(engine.runner("pipe", cid).load()["stages"]["research"]["output"], sort_keys=True)
        real = engine.Runner._merge_research

        def broken(self, rec):
            rec["stages"]["research"]["output"]["sources"] = [{"id": "WRECKED"}]
            raise RuntimeError("merge blew up half way")

        engine.Runner._merge_research = broken
        try:
            got = self._send(cid, key, "identity", "no")
        finally:
            engine.Runner._merge_research = real
        self.assertEqual(got["chosen"], "no", "the decision is the deliverable and it stands")
        rec = engine.runner("pipe", cid).load()
        self.assertEqual(json.dumps(rec["stages"]["research"]["output"], sort_keys=True), before,
                         "and not one byte of the half-finished rebuild was published")
        self.assertTrue(rec["derivedStateStale"], "the course says its views are out of date")
        self.assertIn("nothing else was changed", rec["derivedStateStale"]["note"])

    def test_the_stale_marker_clears_only_after_a_rebuild_that_finishes(self):
        f, cid, key = self._ready("rebuild-recovers")
        real = engine.Runner._merge_research

        def broken(self, rec):
            raise RuntimeError("nope")

        engine.Runner._merge_research = broken
        try:
            self._send(cid, key, "identity", "no")
        finally:
            engine.Runner._merge_research = real
        self.assertTrue(engine.runner("pipe", cid).load().get("derivedStateStale"))

        self._send(cid, key, "role", "partly")
        rec = engine.runner("pipe", cid).load()
        self.assertIsNone(rec.get("derivedStateStale"), "a rebuild that finished clears it")
        self.assertEqual(len(rec["stages"]["research"]["attributionDecisions"]), 2, "both decisions kept")
        att = rec["stages"]["research"]["output"]["sources"][0]["attribution"]
        self.assertEqual({d["about"] for d in att.get("decidedByAPerson") or []}, {"identity", "role"})


class AReopenedDecisionCanBeReplaced(unittest.TestCase):
    """The page read `x.replacing` and nothing ever put it there, so a reopened question had no honest action."""

    def _ready(self):
        f, cid, rec = begin("reopen")
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        rec = wait(cid)
        key = next(iter(rec["stages"]["research"]["attributionHistory"]))
        r = engine.runner("pipe", cid).load()
        h = r["stages"]["research"]["attributionHistory"][key]
        h[-1] = dict(h[-1], detail=dict(h[-1]["detail"], identity_correct="no"))
        engine.runner("pipe", cid).save(r)
        engine.runner("pipe", cid).start("attribution_review", {"action": "attribution_review"})
        wait(cid)
        return f, cid, key

    def _decide(self, cid, key, chosen, replacing=None):
        rec = engine.runner("pipe", cid).load()
        rs = rec["stages"]["research"]
        entry = rs["attribution"][key]
        q = next(x for x in engine.open_questions(entry, (rs.get("attributionResolutions") or {}).get(key))
                 if x["key"] == "identity")
        return engine.record_resolution("pipe", cid, key, "identity", {
            "by": "P", "chosen": chosen, "becauseWords": "w", "reason": "r",
            "sawEvidence": entry["fingerprint"], "sawRevision": q["revision"],
            "replacing": replacing if replacing is not None else q.get("replacing")})

    def test_a_reopened_question_carries_the_decision_it_would_replace(self):
        f, cid, key = self._ready()
        first = self._decide(cid, key, "yes")
        # The review answers differently again on the same evidence: the question reopens.
        r = engine.runner("pipe", cid).load()
        rs = r["stages"]["research"]
        rs["attribution"][key]["unresolvedDisagreements"] = [
            {"aspect": "identity", "key": "identity", "earlier": "yes", "later": "partly",
             "sameEvidence": True, "sameWholeRequest": True}]
        engine.runner("pipe", cid).save(r)
        rec = engine.runner("pipe", cid).load()
        rs = rec["stages"]["research"]
        q = engine.open_questions(rs["attribution"][key], rs["attributionResolutions"][key])[0]
        self.assertEqual(q["replacing"], first["decisionId"], "the page is told which decision it supersedes")
        self.assertEqual(q["previousDecision"]["chosen"], "yes", "and what that decision was")

    def test_deciding_again_supersedes_and_keeps_both(self):
        f, cid, key = self._ready()
        first = self._decide(cid, key, "yes")
        r = engine.runner("pipe", cid).load()
        r["stages"]["research"]["attribution"][key]["unresolvedDisagreements"] = [
            {"aspect": "identity", "key": "identity", "earlier": "yes", "later": "partly",
             "sameEvidence": True, "sameWholeRequest": True}]
        engine.runner("pipe", cid).save(r)
        second = self._decide(cid, key, "no")
        self.assertEqual(second["replaces"], first["decisionId"])
        hist = engine.decision_history(engine.runner("pipe", cid).load(), key, "identity")
        self.assertEqual([h["chosen"] for h in hist], ["yes", "no"], "both kept, in order")

    def test_the_decision_history_reaches_the_screen(self):
        f, cid, key = self._ready()
        self._decide(cid, key, "yes")
        r = engine.runner("pipe", cid).load()
        r["stages"]["research"]["attribution"][key]["unresolvedDisagreements"] = [
            {"aspect": "identity", "key": "identity", "earlier": "yes", "later": "partly"}]
        engine.runner("pipe", cid).save(r)
        r = engine.runner("pipe", cid).load()
        engine.runner("pipe", cid)._merge_research(r)
        att = r["stages"]["research"]["output"]["sources"][0]["attribution"]
        self.assertTrue(att.get("decisionHistory"), "the panel can show every decision made")
        self.assertEqual(att["decisionHistory"][0]["chosen"], "yes")


class EveryDeliveryModeReachesTheWriter(unittest.TestCase):
    """The delivery rules exist in `prompts`; nothing proved they reach the person writing a session.

    A rule that is written but never sent is the same as no rule: the writer plans for a room when the course
    is self-paced, and nobody finds out until a learner is sitting alone with an instruction that assumes a
    teacher is standing there.
    """

    OUTLINE = {"sessions": [{"title": "One", "aim": "a", "minutes": 60, "topics": ["N1"], "proof": "p"}]}

    def _prompt(self, delivery, fmt="course", minutes=60):
        from loom_server import prompts
        brief = {"topics": ["t"], "outcome": "o", "deliveryKey": delivery, "formatKey": fmt,
                 "audience": "adults", "priorKey": "some"}
        plan = {"sessions": 1, "minutes": [minutes], "unit": "session"}
        p, _ = prompts.materials(brief, plan, None, self.OUTLINE, 0)
        return p

    def test_each_mode_sends_its_own_rule_and_not_another(self):
        marks = {"room": "IN A ROOM", "live": "ONLINE AND LIVE", "hybrid": "ROOM AND ONLINE TOGETHER",
                 "self": "SELF-PACED", "blended": "BLENDED"}
        for mode, mark in marks.items():
            p = self._prompt(mode)
            self.assertIn(mark, p, f"{mode} must carry its own rule")
            for other, other_mark in marks.items():
                if other != mode and other_mark not in mark and mark not in other_mark:
                    self.assertNotIn(other_mark, p, f"{mode} must not also carry the {other} rule")

    def test_self_paced_tells_the_writer_there_is_no_teacher(self):
        p = self._prompt("self")
        self.assertIn("no teacher present", p)
        self.assertIn("check one", p, "a self-paced learner needs a way to check their own work")

    def test_hybrid_demands_two_routes_and_says_who_watches_the_online_group(self):
        p = self._prompt("hybrid")
        self.assertIn("two written routes", p)
        self.assertIn("who watches the online group", p)

    def test_live_online_plans_for_a_weak_connection(self):
        self.assertIn("weak connection", self._prompt("live"))

    def test_blended_must_say_which_work_is_live_and_use_the_rest(self):
        p = self._prompt("blended")
        self.assertIn("whether it is live or done alone", p)
        self.assertIn("used in the next live session", p)

    def test_a_mode_loom_does_not_know_adds_no_rule_rather_than_a_wrong_one(self):
        p = self._prompt("teleportation")
        for mark in ("IN A ROOM", "SELF-PACED", "BLENDED", "ROOM AND ONLINE TOGETHER", "ONLINE AND LIVE"):
            self.assertNotIn(mark, p)


class ShortFormatsAreNotTreatedAsCourses(unittest.TestCase):
    """A talk is not a workshop with less time, and a clinic is not a course with a different label."""

    OUTLINE = {"sessions": [{"title": "One", "aim": "a", "minutes": 20, "topics": ["N1"], "proof": "p"}]}

    def _prompt(self, fmt, minutes):
        from loom_server import prompts
        brief = {"topics": ["t"], "outcome": "o", "deliveryKey": "room", "formatKey": fmt,
                 "audience": "adults", "priorKey": "some"}
        return prompts.materials(brief, {"sessions": 1, "minutes": [minutes], "unit": "session"}, None,
                                 {"sessions": [dict(self.OUTLINE["sessions"][0], minutes=minutes)]}, 0)[0]

    def test_a_talk_is_told_not_to_become_a_workshop(self):
        p = self._prompt("talk", 20)
        self.assertIn("Do not force a workshop into it", p)
        self.assertIn("Two activities are enough", p)

    def test_a_talk_is_not_failed_for_having_no_feedback_activity(self):
        self.assertIn("will not send the answer back for", self._prompt("talk", 20))

    def test_a_short_session_of_any_format_is_told_not_to_pad(self):
        self.assertIn("Do not pad it", self._prompt("course", 40))

    def test_a_clinic_is_built_around_what_learners_bring(self):
        p = self._prompt("clinic", 60)
        self.assertIn("CLINIC", p)
        self.assertIn("brings nothing", p, "the teacher needs a plan for the learner who brings nothing")

    def test_a_long_course_session_gets_no_short_format_rule(self):
        p = self._prompt("course", 90)
        for mark in ("Do not force a workshop into it", "Do not pad it", "CLINIC"):
            self.assertNotIn(mark, p)


class PrerequisiteRecursionStops(unittest.TestCase):
    """A map that keeps asking "and what does THAT need?" never finishes. Where it stops must be visible."""

    def test_the_map_records_where_it_stopped_and_what_it_assumed(self):
        f, cid, rec = begin("map-stop")
        m = rec["stages"]["map"]["output"]
        self.assertIn("assumed_entry", m, "what learners are assumed to know already is part of the answer")
        self.assertIn("stop_reason", m, "and so is why the map goes no deeper")

    def test_every_foundation_names_what_it_is_needed_by(self):
        f, cid, rec = begin("map-why")
        for n in rec["stages"]["map"]["output"]["nodes"]:
            if n.get("kind") == "foundation":
                self.assertTrue(n.get("needed_by"), f"{n['id']} must say what it is a foundation for")
                self.assertTrue(str(n.get("why_needed") or "").strip(), f"{n['id']} must say why")

    def test_a_requirement_the_map_does_not_hold_is_an_open_gap_not_a_silent_one(self):
        from loom_server import pipeline
        m = {"nodes": [{"id": "N1", "name": "Later", "role": "required", "kind": "requested",
                        "requires": ["N-MISSING"], "needed_by": ["OUTCOME"], "est_minutes": 30}],
             "assumed_entry": [], "stop_reason": "x"}
        got = pipeline.derive_map(dict(m))["derived"]
        self.assertIn("order", got, "the map still orders what it does hold")
        self.assertNotIn("N-MISSING", got["order"], "a requirement with no node is not invented as one")
        self.assertTrue(got.get("openGaps") or got.get("unresolved") or
                        any("N-MISSING" in str(v) for v in got.values()),
                        "and it is named somewhere rather than dropped in silence")


class ACombinationMustEarnItsPlace(unittest.TestCase):
    """Two topics in one brief is a claim that they belong together. The claim has to be made and checked."""

    def test_the_outline_is_asked_what_each_topic_contributes(self):
        from loom_server import prompts
        brief = {"topics": ["data cleaning", "environmental storytelling"], "outcome": "o",
                 "deliveryKey": "room", "formatKey": "course", "audience": "adults", "priorKey": "some",
                 "mode": "combined"}
        m = {"nodes": [{"id": "N1", "name": "data cleaning", "role": "required", "kind": "requested"},
                       {"id": "N2", "name": "environmental storytelling", "role": "required", "kind": "requested"}],
             "assumed_entry": [], "stop_reason": "x"}
        p, _ = prompts.outline2(brief, {"sessions": 4, "minutes": [90] * 4, "unit": "session", "total": 360}, m, None,
                                {"note": "", "minor": 1, "major": 1}, {"statement": ""}, [])
        low = p.lower()
        self.assertTrue("combin" in low or "together" in low or "integrat" in low,
                        "a combined brief must ask how the topics work together")

    def test_the_research_schema_records_whether_the_combination_is_supported(self):
        from loom_server import prompts
        self.assertIn("combination_evidence", json.dumps(prompts.RESEARCH_SCHEMA))
        enum = json.dumps(prompts.RESEARCH_SCHEMA)
        for v in ("supported", "weak", "none_found", "not_applicable"):
            self.assertIn(v, enum, f"{v} is one of the honest answers about a combination")

    def test_coverage_says_where_each_requested_topic_is_actually_taught(self):
        f, cid, rec = begin("combination-coverage")
        rows = (rec["stages"].get("outline") or {}).get("coverage", {}).get("rows")
        if not rows:
            self.skipTest("this fixture stops before an outline; coverage is tested in the outline tests")
        for r in rows:
            self.assertIn("taughtInSession", r, f"{r.get('name')} must say where it is taught")
